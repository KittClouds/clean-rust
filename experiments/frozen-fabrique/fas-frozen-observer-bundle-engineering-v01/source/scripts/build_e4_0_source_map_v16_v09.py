from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[4]
PROJECT = WORKSPACE / "experiments" / "fas-frozen-observer-bundle-engineering-v01"
PRIOR_MAP = PROJECT / "plans" / "E4-0-IMPLEMENTATION-SOURCE-MAP-v16-v08.md"
OUTPUT = PROJECT / "plans" / "E4-0-IMPLEMENTATION-SOURCE-MAP-v16-v09.md"
RUN_ROOT = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e4-0-v01")
V08_CONTRACT_SHA256 = "ec17befa2a65e0da589ee51792cde3c028e900aa919179b2c9c3365cc20c3e9b"
V08_CONTRACT_BYTES = 54286
V06_ROOT_SHA256 = "7344badf07476d19d9c6228f80d026a112c339e93daa75593e61031f68456e64"
V16_V03_MAP_REL = "experiments/fas-frozen-observer-bundle-engineering-v01/plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v16-v03.md"
V16_V03_MAP_BYTES = 106461
V16_V03_MAP_SHA256 = "b75ce6021d4f52ccf1791d8d473dcb56527dfba3edde16066b98135bb0f004a0"
V16_V03_CONTRACT_REL = "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v16-v02-final.json"
V16_V03_CONTRACT_BYTES = 105950
V16_V03_CONTRACT_SHA256 = "b708b3e0411b4189371fbfd91f330839aa39ef8939e9a622565a47966a1a0c32"
V16_V03_PRESEAL_REL = "experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/track-e-preseal-receipt-v16-v03.json"
V16_V03_PRESEAL_BYTES = 132329
V16_V03_PRESEAL_SHA256 = "c6eddaa8144d57263613f7ba466be4ce396a55de8e70aa2e8bf94ec767de2109"
V16_V03_PRESEAL_STATUS = "E4_0_TRACK_E_PRESEAL_STOP_MISMATCHES_RECORDED_V16_V03"
V16_V03_PRESEAL_ISSUES = ["v16 amendment differs from the canonical flattened v12-v15 lineage or exact preserved no-contact stops"]
V16_V04_MAP_REL = "experiments/fas-frozen-observer-bundle-engineering-v01/plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v16-v04.md"
V16_V04_MAP_BYTES = 110067
V16_V04_MAP_SHA256 = "29c304ce6943d8d982e0ca7bae2d66be3bf2fb4b1d54ed5cec7a0090bf8ac414"
V16_V04_CONTRACT_REL = "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v16-v03-final.json"
V16_V04_CONTRACT_BYTES = 110905
V16_V04_CONTRACT_SHA256 = "44dc5b8fd06874c5478cc7b026d30d543a8c8a0f38697c59ea4ce0ce583d9a06"
V16_V04_PRESEAL_REL = "experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/track-e-preseal-receipt-v16-v04.json"
V16_V04_PRESEAL_BYTES = 136715
V16_V04_PRESEAL_SHA256 = "721478570cd3d9a15645424045046ea788ad572430305cd16e19956eddee6c09"
V16_V04_SEALER_REL = "experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/seal_e4_0_contract_v16_v04.py"
V16_V04_SEALER_BYTES = 17761
V16_V04_SEALER_SHA256 = "87cd4e9aa33ca450d5be4dfe771ae0c21a8acb52344b35efafa206e444eee013"
V16_V04_SEAL_STOP_REL = "experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/contract-seal-stop-v16-v04-v01.json"
V16_V04_SEAL_STOP_BYTES = 2042
V16_V04_SEAL_STOP_SHA256 = "e7fc5c6018470ffc45388ef9f00fe417cdd074e03eb8fcaa60ef691db9c87df2"
V16_V04_SEAL_STOP_STATUS = "E4_0_CONTRACT_SEAL_STOP_DUPLICATE_MEMBER_PATH_V16_V04"
V16_V04_SEAL_STOP_DIAGNOSTIC = "duplicate seal member resolved path: experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/finalize_e4_0_contract_v13.py"
V16_V04_AUTH_BINDINGS = {"path": "experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-auth-issuer-v16-v04/online-parity-bindings-v01.json", "bytes": 4721, "sha256": "17fd15a88d2a0741b6a9350190fc4cf812fa9c63f0fcb6c8fe5a4264e9eb2466"}
V16_V04_AUTH_CONTRACT = {"path": "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v16-v04-final.json", "bytes": 116783, "sha256": "801f7516b4630e62e3770243cedba7d12f12f1c9e9143ab0c2ace1ede6bb8c02"}
V16_V04_AUTH_SEAL = {"path": "experiments/fas-frozen-observer-bundle-engineering-v01/seals/e4-0-contract-v16-v04-seal.json", "bytes": 144298, "sha256": "a4532a304ea4225f6f9a3c6e8dc14572950a9292b817bd0724a1ab38be194bf6", "root_sha256": "5683498ef06e09452252323d4fc5e6b7e9a52974074fefb1d954488dace3a312"}
V16_V04_AUTH_STOP = {"path": "experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-auth-issuer-v16-v04/online-parity-precontact-stop-v01.json", "bytes": 2028, "sha256": "db1c5efe4b441e34b4afb3ea969b14db1e01a1bfd0b9bd3492a0922302ea8229", "status": "PRECONTACT_STOP"}
V16_V04_AUTH_OUTPUT = {"path": "experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-auth-issuer-v16-v04/online-parity-authorization-v01.json", "exists": False}
V16_V04_AUTH_DIAGNOSTIC = "AuthorizationError: v16 amendment does not preserve flattened v12-v14 lineage and exact v15 stop"
V16_V05_AUTH_BINDINGS = {"path": "experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-auth-issuer-v16-v05/online-parity-bindings-v01.json", "bytes": 4721, "sha256": "72b0cd6899e3c05eda706e4ff3c5fb184e5b65ac17247f56258d2d0fe861a313"}
V16_V05_AUTH_CONTRACT = {"path": "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v16-v05-final.json", "bytes": 122699, "sha256": "762fdeb9705e659136ce8f7c2f448d2762c1d8129228b85125d10571ac818574"}
V16_V05_AUTH_SEAL = {"path": "experiments/fas-frozen-observer-bundle-engineering-v01/seals/e4-0-contract-v16-v05-seal.json", "bytes": 150571, "sha256": "37af44de092ca21778b43962b9de106fa7320848384e368a74c689c69f906bb7", "root_sha256": "c2f8d7bf6aa611f18ce886669d5c0bf008f98caf235fc4d98de9af8ea43bfab2"}
V16_V05_AUTH_STOP = {"path": "experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-auth-issuer-v16-v05/online-parity-precontact-stop-v01.json", "bytes": 2259, "sha256": "9ab0b637c15918ca6909728d05403c37349a875e707c3d75a246485b5149da6c", "status": "PRECONTACT_STOP"}
V16_V05_AUTH_OUTPUT = {"path": "experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-auth-issuer-v16-v05/online-parity-authorization-v01.json", "exists": False}
V16_V05_AUTH_DIAGNOSTIC = "AuthorizationError: preserved v06 authorization reference has unexpected contract/stage identity"
V16_V08_MAP_BYTES = 124095
V16_V08_MAP_SHA256 = "8a69757820d9ec8935270ad3cab4005457d1f3726cfa396824e0abe33f03d1f2"
V16_V07_MAP_ATTEMPT = {"path": "experiments/fas-frozen-observer-bundle-engineering-v01/plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v16-v07.md", "bytes": 123177, "sha256": "2c95851c8f5910552edcae1f38dc3cd737b9827f1243bb21211b288e8a2b3a09"}
V16_V07_FINALIZATION_STOP = {"path": "experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/finalization-stop-v16-v07-v01.json", "bytes": 2408, "sha256": "097ffe2dd301b3001227d7fe64fdd34ad6ab7e085cab0457ca44e010d3d9d2e6", "status": "E4_0_V16_V07_FINALIZATION_STOP_RECEIPT_SOURCE_CLOSURE_MISMATCH"}
V16_V07_FINALIZER_ATTEMPT_SOURCE = {"path": "experiments/fas-frozen-observer-bundle-engineering-v01/source/history/finalize_e4_0_contract_v16_v08-attempt-v01.py", "bytes": 99793, "sha256": "b5cfae7e6749886b7f692f989b10338b6b494f8e6d965c34618f935f8a36ea4d"}
V16_V06_MAP_ATTEMPT = {
    "path": "experiments/fas-frozen-observer-bundle-engineering-v01/plans/history/E4-0-IMPLEMENTATION-SOURCE-MAP-v16-v06-attempt-v01.md",
    "bytes": 118234,
    "sha256": "9cf7c759b3eb0df91ccd066e443e0e77c25b59e3ced828d326048b0118fb54fb",
}
V07_MAP_SHA256 = "2b8c88eef79eaa5dff840d6a04844861f6a9a048068a1b514c71642f37e8a02d"
V07_MAP_BYTES = 53298
V08_ROOT_SHA256 = "e0093eacd70ce7cbf3b3a19045683ce5a7f4d4413748003e2d8e1446f131478d"
V08_SEAL_SHA256 = "238d1fdb46ba3d8a9de1ae90e41a9b3c455ba65661bc98e8fe6fa5d21e3d3156"
V08_SEAL_BYTES = 68666
V08_POSTSEAL_AUDIT_SHA256 = "8e2fb068f0ce4acda3d91fe53f4f9b37fab9cffa49a2067ffdd939e95c862898"
V08_AUTH_BINDINGS_SHA256 = "0c3e29a78d2d5eb14ffb573fdf1bc9baa91957488b2f95c7c0fe17412b550cdc"
V08_AUTH_BINDINGS_BYTES = 4719
V08_AUTH_STOP_SHA256 = "99c937b1f8a2242609621b1210828b6ae1411e701cbe2074d655d90328904e4d"
V08_AUTH_STOP_BYTES = 1997
WDDM_PREFLIGHT_SHA256 = "20ad334b87b3c6a36435f71382a906f6009e7427760d617d2d73a3baa380cc34"
WDDM_PREFLIGHT_BYTES = 8151
V08_FIRST_MAP_SHA256 = "e065c482515e41f41e9bcd65b1b85e0bdda25f6ab9e3bd81d091d404f4043ea2"
V08_FIRST_MAP_BYTES = 53441
V08_AUDIT_STOP_MAP_SHA256 = "d1d9647c47743970cd5e9d8122fb2f4a5d25d2c07d19e37c4fbe0fcf25a35d3d"
V08_AUDIT_STOP_MAP_BYTES = 53442
V08_PRESEAL_STOP_SHA256 = "5defca6d7a23f1f767a0d03118594d34998107fdaed6e1db972daec0ed950385"
V08_PRESEAL_STOP_BYTES = 69728
V08_PRESEAL_CANDIDATE_SHA256 = "3fbb3f52d6f193b18abb93039e3eb8fb2606808005fddebdab2245b6603e724a"
V08_PRESEAL_CANDIDATE_BYTES = 54430
V09_MAP_SHA256 = "c79306de009e82a5bdd5bd650e64744d115b870c8c4309dd5863a4d7b339b267"
V09_MAP_BYTES = 65000
V09_CONTRACT_SHA256 = "f973bbd7d5bebeb6a60b8586060c8c65424deefdfce64ddcfd45246ebdfabd44"
V09_CONTRACT_BYTES = 61414
V09_PRESEAL_SHA256 = "7ee376b87c41f727274f58f72f2db524806206ea216b3c18a8d82843e94d1bf8"
V09_PRESEAL_BYTES = 84023
V10_MAP_SHA256 = "6f53cb299ab9aefd0ee3ea7ea485d86f20b6a64acde15ee498a50f3e4efd7945"
V10_MAP_BYTES = 73060
V10_CONTRACT_SHA256 = "c00e140c4cb503717cbf0aa2515f613fde86ac2b81d24a9819d785e9ff959369"
V10_CONTRACT_BYTES = 66628
V10_PRESEAL_SHA256 = "dfc41a61d69384a26ea4c743ba27cf84d48f9859827a32cc6c6caab28aa22f83"
V10_PRESEAL_BYTES = 91652
V10_SEAL_SHA256 = "2e6372ba6d34ef4e2c309abd26b857cd69e3a982e3a78398a099c708e9207efa"
V10_SEAL_BYTES = 84494
V10_SEAL_ROOT_SHA256 = "b9eab12e1ff189c6c9fff3d63ea1e11b4f0e7a54d92a2b57accd39adee5ec5b5"
V10_POSTSEAL_V01_SHA256 = "b82b1c6404a293436e99eee5816f0e14fdd1d28b9da2cab6ec419272c56458d0"
V10_POSTSEAL_V01_BYTES = 91693
V10_POSTSEAL_V02_SHA256 = "e4561320636702663836d39f1deee4320d465efbc00feaea0369754a6a32f221"
V10_POSTSEAL_V02_BYTES = 92830
V10_SEALED_MAP_SHA256 = "d464e0e4898da33afcab6153f7f7df34be9f2a3f9ec499896ac703807f986b6e"
V10_SEALED_MAP_BYTES = 82088
V11_CANDIDATE_MAP_SHA256 = "61df89861d9540641305cdb0020a7bc95772a8adab529e5fdd62898e4c066930"
V11_CANDIDATE_MAP_BYTES = 91198
V12_FAILED_MAP_SHA256 = "697a438d99ae8897a3dcb390783ef8ab65c17bd1ffcca16465ffb7f3a4d74073"
V12_FAILED_MAP_BYTES = 100147
V13_DRAFT_MAP_SHA256 = "a06d436c5cee8305ab65a7cb77f34165f48ccdeee932b788a511a70663c47fc6"
V13_DRAFT_MAP_BYTES = 86052
V13_FINALIZER_SHA256 = "03025d1e0e5ed52e7ef3920db0ef780139944fd209fa9d221ca071b42f16ed11"
V13_FINALIZER_BYTES = 52511
V13_FINALIZATION_STOP_SHA256 = "43e1270f5d395154ab713401558814503dc4fc143048d980447932750fa577dc"
V13_FINALIZATION_STOP_BYTES = 1658
V14_MAP_SHA256 = "40f1d41123dd75093766c01f3e8073f584cf3a7c265d2fba0461ed72ced4fe8f"
V14_MAP_BYTES = 89298
V14_CONTRACT_SHA256 = "9a195eaa7cbbdfff79ee9095c283c52bfb2e78baf40608eab86c0435c443b8f8"
V14_CONTRACT_BYTES = 86587
V14_PRESEAL_SHA256 = "d97d00209cc485d80af1d8a7faa0da15cbdf54a79357b13efe9b458ec4d97995"
V14_PRESEAL_BYTES = 112879
V14_PRESEAL_STATUS = "E4_0_TRACK_E_PRESEAL_STOP_MISMATCHES_RECORDED_V14"
V15_MAP_BYTES = 94630
V15_MAP_SHA256 = "3747444405a905ed8918d7939ce7e968915b02d6ebcee422d588f010d7fe50f1"
V15_CONTRACT_BYTES = 95055
V15_CONTRACT_SHA256 = "a29963988af2c7d1456e403a1cf219a915d29b2b7f4559b44ef175f60aa1d698"
V15_PRESEAL_BYTES = 118505
V15_PRESEAL_SHA256 = "66b9059a9b92c6711d704d1849bb60158003746b394c8d5bb1ebedb4b2a3113b"
V15_PRESEAL_STATUS = "E4_0_TRACK_E_PRESEAL_STOP_MISMATCHES_RECORDED_V15"
V16_FIRST_MAP_BYTES = 100236
V16_FIRST_MAP_SHA256 = "34543f8b437adcc5ae003e1638ff77e0503b0089d39c456bbadc6b1dcff03f07"
V16_FINALIZATION_STOP_BYTES = 1767
V16_FINALIZATION_STOP_SHA256 = "ed84d2392b800a18ad66c38d89dff230d7f71f93900f98a23b92652ee8cee53f"
V16_FINALIZATION_STOP_STATUS = "E4_0_V16_FINALIZATION_STOP_RECEIPT_CLOSURE_MISMATCH"
V15_PRESEAL_ISSUES = [
    "v15 amendment does not exactly preserve v14 lineage and bind its failed-preseal attempt",
    "contract implementation_sources does not exactly bind source-map rows by role",
    "source-test receipt track/path/status differs from its registered identity: 'Predecessor Track E v07 pre-map': expected ('experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/track-e-source-tests-v15.json', 'TRACK_E_SOURCE_TESTS_PASS_V07_PREMAP_SYNTHETIC_AUDITOR'), got ('experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/track-e-source-tests-v14.json', 'TRACK_E_SOURCE_TESTS_PASS_V07_PREMAP_SYNTHETIC_AUDITOR')",
]
V15_TOOLING_V01_BYTES = 2462
V15_TOOLING_V01_SHA256 = "4d30464ff0d24580173cbfb9e3186eb1b97fe8d0a4f4a448150fbba25f9884d5"
V15_TOOLING_V02_BYTES = 2520
V15_TOOLING_V02_SHA256 = "cd588fe105bf05328085cd8fbc86a4099972a2fd9b299a0ee0d13784f3e1f785"
V15_ISSUER_V01_BYTES = 1724
V15_ISSUER_V01_SHA256 = "d012c5c2a0d90fbc2d15037425c73f0a8b6f5e1a7eac1821b1c06efaf50ceb00"
V15_TRACK_E_V01_BYTES = 1916
V15_TRACK_E_V01_SHA256 = "68575fda116794075170b12d38314332fb68a10ee3d9a88e9c4f5f8a3fd9d4ca"
V14_PRESEAL_ISSUES = [
    "v14 amendment does not exactly preserve v13 lineage and bind the failed v13 finalizer attempt",
    "source-test receipt track/path/status differs from its registered identity: 'Predecessor Authorization issuer v13': expected ('experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-auth-issuer-v13/source-tests-v01.json', 'PASS_SYNTHETIC_TESTS'), got ('experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-auth-issuer-v13/source-tests-v02.json', 'PASS_SYNTHETIC_TESTS')",
    "source-test receipt track/path/status differs from its registered identity: 'Predecessor Contract tooling v13': expected ('experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/contract-tooling-source-tests-v12.json', 'PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS'), got ('experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/contract-tooling-source-tests-v13.json', 'PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS')",
    "source-test receipt track/path/status differs from its registered identity: 'Contract tooling v14': expected ('experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/contract-tooling-source-tests-v13.json', 'PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS'), got ('experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/contract-tooling-source-tests-v14.json', 'PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS')",
    "source map must bind exactly one v13 failed-finalization source artifact",
]
V11_CONTRACT_SHA256 = "9cefc7cf9ca8f367bceff3c1c9b7e84ab3e15f684326edf94354e33e3d1fb2fd"
V11_CONTRACT_BYTES = 72068
V11_PRESEAL_SHA256 = "a3ccc4181717af9a84b2e16fc57a7f8819d0fc646918f6f09f760e8bf2c0392d"
V11_PRESEAL_BYTES = 101751
V11_SEAL_SHA256 = "7f27371f3cb886208ff67ea7a19e2ca51577bfbc74e4f6611ca496ab9c13ebcd"
V11_SEAL_BYTES = 90814
V11_SEAL_ROOT_SHA256 = "dc7ec0731a6f637bd8aa6416bd74aba8e074e8bf0c936a1bda830e79c0afa6c3"
V11_POSTSEAL_SHA256 = "09822f935ef94c9307f3a9754dc8a408294de0f77832b7ef09f8e47d56272aa9"
V11_POSTSEAL_BYTES = 102930
POPULATION_ROOT_SHA256 = "27731b483b8242aaef15ca22b97796b7b305a79db9bbb235765e13dcd9d08967"
POPULATION_AUDIT_SHA256 = "7dd3eea3133dbed779071fd14e22df06ff5a0ddce994e4446cf4c6ef7b9cbe5a"
PANEL_ROOT_SHA256 = "6ef00306df0df20ada7b7a86b09567ae46e07f112f66d974d7885e8f1e5d4d95"
PANEL_AUTHORIZATION_SHA256 = "3e3f06bbe12db1bb9608cf56cb1699039d70b6ed79aed757b056e87cc0209d59"
PASS_STATUSES = {
    "TRACK_A_COMPLETE_PREAUTHORIZATION",
    "PASS_SYNTHETIC_SOURCE_AND_CLI_TESTS",
    "TRACK_D_COMPLETE_PREAUTHORIZATION",
    "TRACK_E_SOURCE_TESTS_PASS_PREMAP_UNIT_TESTS",
    "PASS_SYNTHETIC_TESTS",
    "TRACK_E_SOURCE_TESTS_PASS_V07_PREMAP_SYNTHETIC_AUDITOR",
    "TRACK_E_SOURCE_TESTS_PASS_V08_PREMAP_SYNTHETIC_AUDITOR",
    "TRACK_E_SOURCE_TESTS_PASS_V09_PREMAP_SYNTHETIC_AUDITOR",
    "TRACK_E_SOURCE_TESTS_PASS_V10_PREMAP_SYNTHETIC_AUDITOR",
    "TRACK_E_SOURCE_TESTS_PASS_V11_PREMAP_SYNTHETIC_AUDITOR",
    "TRACK_E_SOURCE_TESTS_PASS_V12_PREMAP_SYNTHETIC_AUDITOR",
    "TRACK_E_SOURCE_TESTS_PASS_V13_MAP_V13_PREMAP_SYNTHETIC_AUDITOR",
    "TRACK_E_SOURCE_TESTS_PASS_V14_PREMAP_SYNTHETIC_AUDITOR",
    "TRACK_E_SOURCE_TESTS_PASS_V15_PREMAP_SYNTHETIC_AUDITOR_V02",
    "TRACK_E_SOURCE_TESTS_PASS_V15_PREMAP_SYNTHETIC_AUDITOR_V03",
    "TRACK_E_SOURCE_TESTS_PASS_V16_PREMAP_SYNTHETIC_AUDITOR",
    "TRACK_E_SOURCE_TESTS_PASS_V16_PREMAP_SYNTHETIC_AUDITOR_V02",
    "TRACK_E_SOURCE_TESTS_PASS_V16_PREMAP_SYNTHETIC_AUDITOR_V03",
    "TRACK_E_SOURCE_TESTS_PASS_V16_PREMAP_SYNTHETIC_AUDITOR_V04",
    "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS",
    "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V02",
    "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V03",
    "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V04",
    "PASS_SYNTHETIC_TESTS_V02",
    "PASS_SYNTHETIC_TESTS_V16_V02",
    "PASS_SYNTHETIC_TESTS_V16_V03",
    "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V05",
    "TRACK_E_SOURCE_TESTS_PASS_V16_PREMAP_SYNTHETIC_AUDITOR_V05",
    "TRACK_E_SOURCE_TESTS_PASS_V16_PREMAP_SYNTHETIC_AUDITOR_V06",
    "TRACK_E_SOURCE_TESTS_PASS_V16_PREMAP_SYNTHETIC_AUDITOR_V07",
    "TRACK_E_SOURCE_TESTS_PASS_V16_PREMAP_SYNTHETIC_AUDITOR_V08",
    "TRACK_E_SOURCE_TESTS_PASS_V16_PREMAP_SYNTHETIC_AUDITOR_V09",
    "PASS_SYNTHETIC_TESTS_V16_V04",
    "PASS_SYNTHETIC_TESTS_V16_V05",
    "PASS_SYNTHETIC_TESTS_V16_V06",
    "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V06",
    "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V07",
    "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V08",
    "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V09",
    "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS",
    "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V02",
}
CURRENT_RECEIPT_STATUSES = {
    "Track B v05": "PASS_SYNTHETIC_SOURCE_AND_CLI_TESTS",
    "Predecessor Track E v15 pre-map attempt 1": "TRACK_E_SOURCE_TESTS_PASS_V15_PREMAP_SYNTHETIC_AUDITOR_V02",
    "Predecessor Track E v15 pre-map attempt 2": "TRACK_E_SOURCE_TESTS_PASS_V15_PREMAP_SYNTHETIC_AUDITOR_V03",
    "Initial Authorization issuer v15": "PASS_SYNTHETIC_TESTS",
    "Authorization issuer v15": "PASS_SYNTHETIC_TESTS_V02",
    "Initial Contract tooling v15": "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS",
    "Predecessor Contract tooling v15 v02": "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V02",
    "Contract tooling v15": "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V03",
    "Initial Track E v16 pre-map": "TRACK_E_SOURCE_TESTS_PASS_V16_PREMAP_SYNTHETIC_AUDITOR",
    "Predecessor Track E v16 pre-map v02": "TRACK_E_SOURCE_TESTS_PASS_V16_PREMAP_SYNTHETIC_AUDITOR_V02",
    "Track E v16 pre-map": "TRACK_E_SOURCE_TESTS_PASS_V16_PREMAP_SYNTHETIC_AUDITOR_V03",
    "Track E v16 pre-map v04 v02": "TRACK_E_SOURCE_TESTS_PASS_V16_PREMAP_SYNTHETIC_AUDITOR_V04",
    "Track E v16 pre-map v05": "TRACK_E_SOURCE_TESTS_PASS_V16_PREMAP_SYNTHETIC_AUDITOR_V05",
    "Authorization issuer v16": "PASS_SYNTHETIC_TESTS",
    "Authorization issuer v16 v02": "PASS_SYNTHETIC_TESTS_V16_V02",
    "Authorization issuer v16 v03": "PASS_SYNTHETIC_TESTS_V16_V03",
    "Initial Contract tooling v16": "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS",
    "Predecessor Contract tooling v16 v02": "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V02",
    "Contract tooling v16": "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V03",
    "Contract tooling v16 v04 v02": "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V04",
    "Contract tooling v16 v05": "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V05",
    "Track E v16 pre-map v06": "TRACK_E_SOURCE_TESTS_PASS_V16_PREMAP_SYNTHETIC_AUDITOR_V06",
    "Authorization issuer v16 v04": "PASS_SYNTHETIC_TESTS_V16_V04",
    "Contract tooling v16 v06": "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V06",
    "Track E v16 pre-map v07": "TRACK_E_SOURCE_TESTS_PASS_V16_PREMAP_SYNTHETIC_AUDITOR_V07",
    "Authorization issuer v16 v05": "PASS_SYNTHETIC_TESTS_V16_V05",
    "Contract tooling v16 v07": "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V07",
    "Authorization issuer v16 v06": "PASS_SYNTHETIC_TESTS_V16_V06",
    "Contract tooling v16 v08": "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V08",
    "Contract tooling v16 v09": "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V09",
    "Track E v16 pre-map v08": "TRACK_E_SOURCE_TESTS_PASS_V16_PREMAP_SYNTHETIC_AUDITOR_V08",
    "Track E v16 pre-map v09": "TRACK_E_SOURCE_TESTS_PASS_V16_PREMAP_SYNTHETIC_AUDITOR_V09",
}


def digest(path: Path) -> tuple[int, str]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1 << 20):
            size += len(chunk)
            h.update(chunk)
    return size, h.hexdigest()


def parse_tables(path: Path) -> list[tuple[list[str], list[list[str]]]]:
    tables: list[tuple[list[str], list[list[str]]]] = []
    header: list[str] | None = None
    rows: list[list[str]] = []

    def close() -> None:
        nonlocal header, rows
        if header is not None and rows:
            tables.append((header, rows))
        header, rows = None, []

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not (line.startswith("|") and line.endswith("|")):
            close()
            continue
        cells = [cell.strip().strip("` ") for cell in line.strip("|").split("|")]
        if cells and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells):
            continue
        if header is None:
            header = cells
        elif len(cells) == len(header):
            rows.append(cells)
        else:
            raise RuntimeError(f"malformed Markdown table row in {path}")
    close()
    return tables


def table(path: Path, wanted: list[str]) -> list[list[str]]:
    norm = lambda items: ["".join(x.lower().split()).replace("-", "") for x in items]
    found = [rows for header, rows in parse_tables(path) if norm(header) == norm(wanted)]
    if len(found) != 1:
        raise RuntimeError(f"expected exactly one table {wanted} in {path}; found {len(found)}")
    return found[0]


def resolve_bound(value: str) -> Path:
    candidate = Path(value)
    path = candidate if candidate.is_absolute() else WORKSPACE / candidate
    return path.resolve(strict=True)


def verify_row(path_text: str, expected_size: str, expected_sha: str) -> tuple[int, str]:
    path = resolve_bound(path_text)
    size, actual = digest(path)
    if not expected_size.isdecimal() or size != int(expected_size) or actual != expected_sha:
        raise RuntimeError(f"carried predecessor identity changed: {path_text}")
    return size, actual


def project_rel(path: Path) -> str:
    return path.resolve().relative_to(WORKSPACE.resolve()).as_posix()


def canonical_key(path: Path) -> str:
    return unicodedata.normalize("NFC", str(path.resolve(strict=True))).casefold()


def receipt_source_bindings(track: str, payload: dict) -> list[dict]:
    if track.startswith("Track B"):
        bindings = payload.get("bound_sources")
    elif track.startswith("Track C") or track.startswith("Track D") or track.startswith("Authorization issuer"):
        bindings = payload.get("source_files")
    elif track.startswith("Track E v08") or track.startswith("Track E v09") or track.startswith("Track E v10") or track.startswith("Track E v11") or track.startswith("Track E v15") or track.startswith("Track E v16"):
        bindings = payload.get("sources")
    elif track.startswith("Contract tooling"):
        bindings = payload.get("source_bindings")
    else:
        return []
    if isinstance(bindings, dict):
        bindings = [{"path": key, **value} for key, value in bindings.items()]
    if not isinstance(bindings, list) or not bindings:
        raise RuntimeError(f"source-test receipt has no source bindings: {track}")
    return bindings


def verify_receipt_source_bindings(track: str, payload: dict, source_rows: list[tuple[str, Path, str]]) -> None:
    by_rel = {rel: (path, *digest(path)) for rel, path, _role in source_rows}
    seen: set[str] = set()
    for row in receipt_source_bindings(track, payload):
        rel = str(row.get("path", ""))
        if rel.startswith("experiments/"):
            canonical_rel = rel
        else:
            canonical_rel = f"experiments/fas-frozen-observer-bundle-engineering-v01/{rel}"
        if canonical_rel not in by_rel:
            raise RuntimeError(f"receipt source is absent from current source closure: {track}: {rel}")
        if canonical_rel in seen:
            raise RuntimeError(f"receipt repeats a tested source identity: {track}: {rel}")
        _path, actual_size, actual_sha = by_rel[canonical_rel]
        if row.get("bytes") != actual_size or row.get("sha256") != actual_sha:
            raise RuntimeError(f"receipt tested source differs from current source closure: {track}: {rel}")
        seen.add(canonical_rel)
    expected: set[str]
    if track.startswith("Track B"):
        names = {
            "e4_runner_common_v05.py", "e4_runner_artifacts_v05.py", "e4_gpu_lease_v04.py",
            "e4_runner_modes_v05.py", "e4_online_parity_v05.py", "test_e4_runner_v05.py",
        }
        expected = {rel for rel in by_rel if any(rel.endswith("/" + name) for name in names)}
    elif track.startswith("Track C"):
        expected = {rel for rel in by_rel if "/source/scripts/e4_fresh_scorer_v04/" in rel}
    elif track.startswith("Track D"):
        expected = {rel for rel in by_rel if "/source/scripts/e4_independent_audit_v04/" in rel}
    elif track.startswith("Track E v08"):
        expected = {rel for rel in by_rel if rel.endswith((
            "/audits/e4-0-track-e/audit_e4_0_track_e_v08.py",
            "/audits/e4-0-track-e/test_audit_e4_0_track_e_v08.py",
        ))}
    elif track.startswith("Track E v09"):
        expected = {rel for rel in by_rel if rel.endswith((
            "/audits/e4-0-track-e/audit_e4_0_track_e_v09.py",
            "/audits/e4-0-track-e/test_audit_e4_0_track_e_v09.py",
        ))}
    elif track.startswith("Track E v10"):
        expected = {rel for rel in by_rel if rel.endswith((
            "/audits/e4-0-track-e/audit_e4_0_track_e_v10.py",
            "/audits/e4-0-track-e/test_audit_e4_0_track_e_v10.py",
        ))}
    elif track.startswith("Track E v11"):
        expected = {rel for rel in by_rel if rel.endswith((
            "/audits/e4-0-track-e/audit_e4_0_track_e_v11.py",
            "/audits/e4-0-track-e/test_audit_e4_0_track_e_v11.py",
        ))}
    elif track.startswith("Track E v15"):
        expected = {rel for rel in by_rel if rel.endswith((
            "/audits/e4-0-track-e/audit_e4_0_track_e_v15_v02.py",
            "/audits/e4-0-track-e/test_audit_e4_0_track_e_v15_v02.py",
        ))}
    elif track == "Track E v16 pre-map":
        expected = {rel for rel in by_rel if rel.endswith((
            "/audits/e4-0-track-e/audit_e4_0_track_e_v16_v03.py",
            "/audits/e4-0-track-e/test_audit_e4_0_track_e_v16_v03.py",
        ))}
    elif track.startswith("Track E v16 pre-map v05"):
        expected = {rel for rel in by_rel if rel.endswith((
            "/audits/e4-0-track-e/audit_e4_0_track_e_v16_v05.py",
            "/audits/e4-0-track-e/test_audit_e4_0_track_e_v16_v05.py",
        ))}
    elif track.startswith("Track E v16 pre-map v06"):
        expected = {rel for rel in by_rel if rel.endswith((
            "/audits/e4-0-track-e/audit_e4_0_track_e_v16_v06.py",
            "/audits/e4-0-track-e/test_audit_e4_0_track_e_v16_v06.py",
        ))}
    elif track.startswith("Track E v16 pre-map v07"):
        expected = {rel for rel in by_rel if rel.endswith((
            "/audits/e4-0-track-e/audit_e4_0_track_e_v16_v07.py",
            "/audits/e4-0-track-e/test_audit_e4_0_track_e_v16_v07.py",
        ))}
    elif track.startswith("Track E v16 pre-map v04"):
        expected = {rel for rel in by_rel if rel.endswith((
            "/audits/e4-0-track-e/audit_e4_0_track_e_v16_v04.py",
            "/audits/e4-0-track-e/test_audit_e4_0_track_e_v16_v04.py",
        ))}
    elif track.startswith("Authorization issuer v15"):
        expected = {rel for rel in by_rel if rel.endswith((
            "/source/scripts/issue_e4_stage_authorization_v15.py",
            "/source/tests/test_e4_stage_authorization_v15.py",
        ))}
    elif track.startswith("Authorization issuer v16"):
        suffixes = (
            ("/source/scripts/issue_e4_stage_authorization_v16_v06.py",
             "/source/tests/test_e4_stage_authorization_v16_v06.py")
            if track.endswith("v06") else
            ("/source/scripts/issue_e4_stage_authorization_v16_v05.py",
             "/source/tests/test_e4_stage_authorization_v16_v05.py")
            if track.endswith("v05") else
            ("/source/scripts/issue_e4_stage_authorization_v16_v04.py",
             "/source/tests/test_e4_stage_authorization_v16_v04.py")
            if track.endswith("v04") else
            ("/source/scripts/issue_e4_stage_authorization_v16_v03.py",
             "/source/tests/test_e4_stage_authorization_v16_v03.py")
            if track.endswith("v03") else
            ("/source/scripts/issue_e4_stage_authorization_v16_v02.py",
             "/source/tests/test_e4_stage_authorization_v16_v02.py")
            if track.endswith("v02") else
            ("/source/scripts/issue_e4_stage_authorization_v16.py",
             "/source/tests/test_e4_stage_authorization_v16.py")
        )
        expected = {rel for rel in by_rel if rel.endswith(suffixes)}
    elif track.startswith("Contract tooling v15"):
        names = {"build_e4_0_source_map_v15.py", "finalize_e4_0_contract_v15.py",
                 "seal_e4_0_contract_v15.py", "test_e4_0_contract_v15.py"}
        expected = {rel for rel in by_rel if any(rel.endswith("/" + name) for name in names)}
    elif track == "Contract tooling v16":
        names = {"build_e4_0_source_map_v16_v03.py", "finalize_e4_0_contract_v16_v03.py",
                 "seal_e4_0_contract_v16_v02.py", "test_e4_0_contract_v16_v03.py"}
        expected = {rel for rel in by_rel if any(rel.endswith("/" + name) for name in names)}
    elif track.startswith("Contract tooling v16 v04"):
        names = {"build_e4_0_source_map_v16_v04.py", "finalize_e4_0_contract_v16_v04.py",
                 "seal_e4_0_contract_v16_v03.py", "test_e4_0_contract_v16_v04.py"}
        expected = {rel for rel in by_rel if any(rel.endswith("/" + name) for name in names)}
    elif track.startswith("Contract tooling v16 v05"):
        names = {"build_e4_0_source_map_v16_v05.py", "finalize_e4_0_contract_v16_v05.py",
                 "seal_e4_0_contract_v16_v04.py", "test_e4_0_contract_v16_v05.py"}
        expected = {rel for rel in by_rel if any(rel.endswith("/" + name) for name in names)}
    elif track.startswith("Contract tooling v16 v06"):
        names = {"build_e4_0_source_map_v16_v06.py", "finalize_e4_0_contract_v16_v06.py",
                 "seal_e4_0_contract_v16_v05.py", "test_e4_0_contract_v16_v06.py"}
        expected = {rel for rel in by_rel if any(rel.endswith("/" + name) for name in names)}
    elif track.startswith("Contract tooling v16 v07"):
        names = {"build_e4_0_source_map_v16_v07.py", "finalize_e4_0_contract_v16_v07.py",
                 "seal_e4_0_contract_v16_v06.py", "test_e4_0_contract_v16_v07.py"}
        expected = {rel for rel in by_rel if any(rel.endswith("/" + name) for name in names)}
    elif track.startswith("Contract tooling v16 v09"):
        names = {"build_e4_0_source_map_v16_v09.py", "finalize_e4_0_contract_v16_v09.py",
                 "seal_e4_0_contract_v16_v08.py", "test_e4_0_contract_v16_v09.py"}
        expected = {rel for rel in by_rel if any(rel.endswith("/" + name) for name in names)}
    elif track.startswith("Contract tooling v16 v08"):
        names = {"build_e4_0_source_map_v16_v08.py", "finalize_e4_0_contract_v16_v08.py",
                 "seal_e4_0_contract_v16_v07.py", "test_e4_0_contract_v16_v08.py"}
        expected = {rel for rel in by_rel if any(rel.endswith("/" + name) for name in names)}
    elif track.startswith("Track E v16 pre-map v09"):
        expected = {rel for rel in by_rel if rel.endswith((
            "/audits/e4-0-track-e/audit_e4_0_track_e_v16_v09.py",
            "/audits/e4-0-track-e/test_audit_e4_0_track_e_v16_v09.py",
        ))}
    elif track.startswith("Track E v16 pre-map v08"):
        expected = {rel for rel in by_rel if rel.endswith((
            "/audits/e4-0-track-e/audit_e4_0_track_e_v16_v08.py",
            "/audits/e4-0-track-e/test_audit_e4_0_track_e_v16_v08.py",
        ))}
    else:
        return
    if seen != expected:
        missing, extra = sorted(expected - seen), sorted(seen - expected)
        raise RuntimeError(f"receipt source closure is not exact for {track}: missing={missing}, extra={extra}")


def validate_v08_authorization_stop(payload: dict) -> None:
    """Validate the exact preserved diagnostic and its no-contact disposition."""
    if (payload.get("status") != "E4_0_V08_AUTHORIZATION_STOP_POPULATION_AUDIT_SCHEMA_MISMATCH"
            or payload.get("stop_class") != "PRECONTACT_AUTHORIZATION_VERIFIER_SCHEMA_MISMATCH"
            or payload.get("error") != "AuthorizationError: preserved population audit receipt is not the exact truth-closed pass"
            or payload.get("model_contact") is not False
            or payload.get("tokenizer_contact") is not False
            or payload.get("cuda_initialized") is not False
            or payload.get("gpu_lease_acquired") is not False
            or payload.get("feature_cache_created") is not False
            or payload.get("labels_opened") is not False
            or payload.get("authorization_output_written") is not False
            or payload.get("authorization_output_exists") is not False):
        raise RuntimeError("preserved v08 authorization attempt is not the exact no-contact preflight stop")


def validate_v14_preseal_stop(payload: dict) -> None:
    """Require the exact preserved v14 diagnostic schema and no-contact values."""
    absent_contact_fields = (
        "authorization_written", "tokenizer_contact", "model_contact", "cuda_initialized",
        "gpu_lease_acquired", "feature_cache_created", "labels_opened",
    )
    if (payload.get("status") != V14_PRESEAL_STATUS
            or payload.get("issues") != V14_PRESEAL_ISSUES
            or payload.get("pass") is not False
            or payload.get("final_seal") is not None
            or payload.get("population_truth_files_opened") is not False
            or payload.get("template_or_joint_truth_opened") is not False
            or any(key in payload for key in absent_contact_fields)):
        raise RuntimeError("preserved failed v14 preseal receipt does not match its exact no-contact findings")


def collect_sources() -> list[tuple[str, Path, str]]:
    baseline_path = PROJECT / "contracts" / "e4-0-contract-v11-final.json"
    baseline_size, baseline_sha = digest(baseline_path)
    if baseline_size != V11_CONTRACT_BYTES or baseline_sha != V11_CONTRACT_SHA256:
        raise RuntimeError("preserved v11 sealed contract identity changed")
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    sealed_map_path = PROJECT / "plans" / "E4-0-IMPLEMENTATION-SOURCE-MAP-v10.md"
    sealed_map_size, sealed_map_sha = digest(sealed_map_path)
    map_design = baseline.get("design_inputs", {})
    if (sealed_map_sha != V10_SEALED_MAP_SHA256 or sealed_map_size != V10_SEALED_MAP_BYTES
            or map_design.get("implementation_source_map_v10_sha256") != sealed_map_sha
            or map_design.get("implementation_source_map_v10_bytes") != sealed_map_size):
        raise RuntimeError("sealed v11 contract-bound v10 source-map identity mismatch")
    prior_map_size, prior_map_sha = digest(PRIOR_MAP)
    if prior_map_sha != V16_V08_MAP_SHA256 or prior_map_size != V16_V08_MAP_BYTES:
        raise RuntimeError("preserved v16-v06 sealed source-map identity changed")

    rows: dict[str, tuple[Path, str]] = {}
    for old_path, old_size, old_sha, role in table(PRIOR_MAP, ["Path", "Bytes", "SHA-256", "Role"]):
        verify_row(old_path, old_size, old_sha)
        if Path(old_path).is_absolute():
            continue
        normalized_role = re.sub(r"^(?:Preserved v06 predecessor input: )+", "", role)
        normalized_role = re.sub(r"^(?:Preserved v11 predecessor source: )+", "", normalized_role)
        rows[old_path] = (resolve_bound(old_path), normalized_role)

    directory_roles = {
        PROJECT / "source" / "scripts" / "e4_independent_audit_v04": "Track D v04 independent stage/replay auditor and tests",
        PROJECT / "source" / "scripts" / "e4_fresh_scorer_v04": "Track C v04 frozen fresh qualification scorer and tests",
    }
    for root, role in directory_roles.items():
        if not root.is_dir():
            raise RuntimeError(f"required inherited source directory missing: {root}")
        for path in root.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix in {".py", ".md", ".toml", ".lock", ".rs"}:
                rows[project_rel(path)] = (path, role)

    explicit_roles = {
        "source/scripts/e4_online_parity_v05.py": "Track B v05 parity/feature runner entrypoint",
        "source/scripts/e4_runner_common_v05.py": "Track B v05 stage identity and validation",
        "source/scripts/e4_runner_artifacts_v05.py": "Track B v05 artifact custody and sealing",
        "source/scripts/e4_runner_modes_v05.py": "Track B v05 parity and feature modes",
        "source/scripts/e4_gpu_lease_v04.py": "Track B v04 WDDM-aware Type-C CUDA lease/resource telemetry",
        "source/tests/test_e4_runner_v05.py": "Track B v05 synthetic-only runtime and WDDM lease tests",
        "source/scripts/issue_e4_stage_authorization_v16.py": "Track E v16 staged authorization issuer",
        "source/tests/test_e4_stage_authorization_v16.py": "Track E v16 authorization issuer tests",
        "source/scripts/issue_e4_stage_authorization_v16_v02.py": "Track E v16-v02 staged authorization issuer with complete sealed-lineage validation",
        "source/tests/test_e4_stage_authorization_v16_v02.py": "Track E v16-v02 authorization issuer synthetic tests",
        "source/scripts/issue_e4_stage_authorization_v16_v03.py": "Track E v16-v03 staged authorization issuer bound to the current contract and stop history",
        "source/tests/test_e4_stage_authorization_v16_v03.py": "Track E v16-v03 authorization issuer synthetic tests",
        "source/scripts/issue_e4_stage_authorization_v16_v04.py": "Track E v16-v04 staged authorization issuer bound to exact contract seal and failed seal-attempt history",
        "source/tests/test_e4_stage_authorization_v16_v04.py": "Track E v16-v04 authorization issuer synthetic tests",
        "source/scripts/issue_e4_stage_authorization_v16_v05.py": "Track E v16-v05 issuer with exact sealed no-contact lineage validation",
        "source/tests/test_e4_stage_authorization_v16_v05.py": "Track E v16-v05 issuer regression tests against the actual sealed predecessor schema",
        "source/scripts/issue_e4_stage_authorization_v16_v06.py": "Track E v16-v06 issuer with explicit historical authorization identity validation",
        "source/tests/test_e4_stage_authorization_v16_v06.py": "Track E v16-v06 issuer regression tests against the preserved v01 identity index",
        "source/scripts/build_e4_0_source_map_v16.py": "Preserved initial v16 source-map builder associated with tooling receipt v16-v01",
        "source/scripts/finalize_e4_0_contract_v16.py": "Preserved initial v16 contract finalizer associated with tooling receipt v16-v01",
        "source/scripts/seal_e4_0_contract_v16.py": "Preserved initial v16 contract sealer associated with tooling receipt v16-v01",
        "source/scripts/test_e4_0_contract_v16.py": "Preserved initial v16 tooling tests associated with tooling receipt v16-v01",
        "audits/e4-0-track-e/audit_e4_0_track_e_v16.py": "Preserved initial v16 independent auditor associated with Track E receipt v28",
        "audits/e4-0-track-e/test_audit_e4_0_track_e_v16.py": "Preserved initial v16 auditor tests associated with Track E receipt v28",
        "source/scripts/build_e4_0_source_map_v16_v02.py": "v16 source-map builder with exact v15 failed-preseal lineage",
        "source/scripts/finalize_e4_0_contract_v16_v02.py": "v16 contract finalizer with v06 scientific invariance checks",
        "source/scripts/seal_e4_0_contract_v16_v02.py": "v16 workspace-rooted contract sealer",
        "source/scripts/test_e4_0_contract_v16_v02.py": "v16 contract finalizer/sealer synthetic closure tests",
        "source/scripts/build_e4_0_source_map_v16_v03.py": "v16-v02 source-map builder preserving the first v16 map and finalizer stop",
        "source/scripts/finalize_e4_0_contract_v16_v03.py": "v16-v02 contract finalizer with version-specific receipt source closure",
        "source/scripts/test_e4_0_contract_v16_v03.py": "v16-v02 contract finalizer/sealer synthetic closure tests",
        "source/scripts/finalize_e4_0_contract_v13.py": "Preserved v13 finalizer source for the pre-finalization status-registry stop",
        "audits/e4-0-track-e/audit_e4_0_track_e_v15.py": "Independent Track E v15 contract/source audit",
        "audits/e4-0-track-e/test_audit_e4_0_track_e_v15.py": "Independent Track E v15 audit tests",
        "audits/e4-0-track-e/audit_e4_0_track_e_v15_v02.py": "Independent Track E v15 v02 contract/source audit",
        "audits/e4-0-track-e/test_audit_e4_0_track_e_v15_v02.py": "Independent Track E v15 v02 audit tests",
        "audits/e4-0-track-e/audit_e4_0_track_e_v16.py": "Preserved initial Track E v16 contract/source audit associated with receipt v28",
        "audits/e4-0-track-e/test_audit_e4_0_track_e_v16.py": "Preserved initial Track E v16 audit tests associated with receipt v28",
        "audits/e4-0-track-e/audit_e4_0_track_e_v16_v02.py": "Independent Track E v16 v02 contract/source audit",
        "audits/e4-0-track-e/test_audit_e4_0_track_e_v16_v02.py": "Independent Track E v16 v02 audit tests",
        "audits/e4-0-track-e/audit_e4_0_track_e_v16_v03.py": "Independent Track E v16 v03 contract/source audit",
        "audits/e4-0-track-e/test_audit_e4_0_track_e_v16_v03.py": "Independent Track E v16 v03 audit tests",
        "source/scripts/build_e4_0_source_map_v16_v04.py": "v16-v03 source-map builder with exact failed v16-v02 attempt history",
        "source/scripts/finalize_e4_0_contract_v16_v04.py": "v16-v03 contract finalizer with complete no-contact amendment lineage",
        "source/scripts/seal_e4_0_contract_v16_v03.py": "v16-v03 workspace-rooted contract sealer",
        "source/scripts/test_e4_0_contract_v16_v04.py": "v16-v03 contract finalizer/sealer synthetic closure tests",
        "audits/e4-0-track-e/audit_e4_0_track_e_v16_v04.py": "Independent Track E v16 v04 contract/source audit",
        "audits/e4-0-track-e/test_audit_e4_0_track_e_v16_v04.py": "Independent Track E v16 v04 audit tests",
        "source/scripts/build_e4_0_source_map_v16_v05.py": "v16-v04 source-map builder preserving the v16-v03 candidate and stop",
        "source/scripts/finalize_e4_0_contract_v16_v05.py": "v16-v04 contract finalizer with exact new failed-attempt lineage",
        "source/scripts/seal_e4_0_contract_v16_v04.py": "v16-v04 workspace-rooted contract sealer",
        "source/scripts/test_e4_0_contract_v16_v05.py": "v16-v04 contract finalizer/sealer synthetic closure tests",
        "audits/e4-0-track-e/audit_e4_0_track_e_v16_v05.py": "Independent Track E v16 v05 contract/source audit",
        "audits/e4-0-track-e/test_audit_e4_0_track_e_v16_v05.py": "Independent Track E v16 v05 audit tests",
        "source/scripts/build_e4_0_source_map_v16_v06.py": "v16-v05 source-map builder preserving the v16-v04 failed seal attempt",
        "source/scripts/finalize_e4_0_contract_v16_v06.py": "v16-v05 contract finalizer with exact failed-seal lineage",
        "source/scripts/seal_e4_0_contract_v16_v05.py": "v16-v05 sealer that collapses exact source/input path overlap after identity verification",
        "source/scripts/test_e4_0_contract_v16_v06.py": "v16-v05 tooling tests including source/input overlap regression",
        "audits/e4-0-track-e/audit_e4_0_track_e_v16_v06.py": "Independent Track E v16 v06 contract/source audit",
        "audits/e4-0-track-e/test_audit_e4_0_track_e_v16_v06.py": "Independent Track E v16 v06 audit tests",
        "source/scripts/build_e4_0_source_map_v16_v07.py": "v16-v06 source-map builder preserving the failed v16-v04 authorization stop",
        "source/scripts/finalize_e4_0_contract_v16_v07.py": "v16-v06 contract finalizer with exact authorizer-stop lineage",
        "source/scripts/seal_e4_0_contract_v16_v06.py": "v16-v06 workspace-rooted contract sealer",
        "source/scripts/test_e4_0_contract_v16_v07.py": "v16-v06 finalizer, sealer, and authorizer-lineage tests",
        "audits/e4-0-track-e/audit_e4_0_track_e_v16_v07.py": "Independent Track E v16 v07 contract/source audit",
        "audits/e4-0-track-e/test_audit_e4_0_track_e_v16_v07.py": "Independent Track E v16 v07 audit tests",
        "source/scripts/build_e4_0_source_map_v16_v08.py": "v16-v07 source-map builder preserving the sealed v16-v06 map and failed v16-v05 authorization attempt",
        "source/scripts/finalize_e4_0_contract_v16_v08.py": "v16-v06 contract finalizer with exact v16-v05 failed authorization lineage",
        "source/scripts/seal_e4_0_contract_v16_v07.py": "v16-v06 workspace-rooted contract sealer",
        "source/scripts/test_e4_0_contract_v16_v08.py": "v16-v06 finalizer, sealer, and failed authorization lineage tests",
        "source/scripts/build_e4_0_source_map_v16_v09.py": "v16-v08 source-map builder preserving the failed preseal candidate, map, and audit receipt",
        "source/scripts/finalize_e4_0_contract_v16_v09.py": "v16-v07 contract finalizer repairing source-role projections and historical JSON field shapes",
        "source/scripts/seal_e4_0_contract_v16_v08.py": "v16-v07 workspace-rooted contract sealer",
        "source/scripts/test_e4_0_contract_v16_v09.py": "v16-v07 contract/source-map/sealer synthetic regression tests",
        "audits/e4-0-track-e/audit_e4_0_track_e_v16_v09.py": "Independent Track E v16 v09 contract/source audit",
        "audits/e4-0-track-e/test_audit_e4_0_track_e_v16_v09.py": "Independent Track E v16 v09 audit tests",
        "audits/e4-0-track-e/audit_e4_0_track_e_v16_v08.py": "Preserved v16-v08 auditor source bound by failed-preseal history",
        "audits/e4-0-track-e/test_audit_e4_0_track_e_v16_v08.py": "Preserved v16-v08 auditor tests bound by failed-preseal history",
        "source/scripts/build_e4_0_source_map_v16_v08.py": "Preserved v16-v08 source-map builder bound by failed-preseal history",
        "source/scripts/finalize_e4_0_contract_v16_v08.py": "Preserved v16-v08 finalizer source bound by failed-preseal history",
        "source/scripts/seal_e4_0_contract_v16_v07.py": "Preserved v16-v08 contract sealer source",
        "source/scripts/test_e4_0_contract_v16_v08.py": "Preserved v16-v08 contract tooling tests",
        "audits/e4-0-track-e/audit_e4_0_track_e_v16_v08.py": "Independent Track E v16 v08 contract/source audit",
        "audits/e4-0-track-e/test_audit_e4_0_track_e_v16_v08.py": "Independent Track E v16 v08 audit tests",
        "audits/e4-0-track-b-v03/attempt-note-v01.json": "Track B v03 repair lineage and unbound-v02 provenance note",
    }
    for rel, role in explicit_roles.items():
        path = PROJECT / rel
        if not path.is_file():
            raise RuntimeError(f"required source closure member missing: {path}")
        rows[project_rel(path)] = (path, role)

    return [(rel, path, role) for rel, (path, role) in sorted(rows.items(), key=lambda item: item[0].encode("utf-8"))]


def collect_inputs() -> list[tuple[str, Path, str]]:
    rows: dict[str, tuple[Path, str]] = {}
    v10_contract_path = PROJECT / "contracts/e4-0-contract-v10-final.json"
    v10_seal_path = PROJECT / "seals/e4-0-contract-v10-seal.json"
    v10_preseal_path = PROJECT / "audits/e4-0-track-e/track-e-preseal-receipt-v10.json"
    v10_stop1_path = PROJECT / "audits/e4-0-track-e/track-e-postseal-receipt-v10.json"
    v10_stop2_path = PROJECT / "audits/e4-0-track-e/track-e-postseal-receipt-v10-v02.json"
    v11_contract_path = PROJECT / "contracts/e4-0-contract-v11-final.json"
    v11_seal_path = PROJECT / "seals/e4-0-contract-v11-seal.json"
    v11_preseal_path = PROJECT / "audits/e4-0-track-e/track-e-preseal-receipt-v11.json"
    v11_stop_path = PROJECT / "audits/e4-0-track-e/track-e-postseal-receipt-v11.json"
    for old_path, old_size, old_sha, role in table(PRIOR_MAP, ["Input Path", "Bytes", "SHA-256", "Role"]):
        verify_row(old_path, old_size, old_sha)
        normalized_role = re.sub(r"^(?:Preserved v06 predecessor input: )+", "", role)
        rows[old_path] = (resolve_bound(old_path), normalized_role)

    prior_map_size, prior_map_sha = digest(PRIOR_MAP)
    if prior_map_size != V16_V08_MAP_BYTES or prior_map_sha != V16_V08_MAP_SHA256:
        raise RuntimeError("preserved v16-v08 source-map identity changed")
    rows[project_rel(PRIOR_MAP)] = (PRIOR_MAP, "Exact v16-v08 source map; immediate contract/source-closure predecessor.")

    inputs = {
        "audits/e4-0-execution/online-parity-precontact-stop-v01.json": "Preserved v06 pre-contact plumbing stop; no runtime/model/CUDA contact occurred.",
        "contracts/e4-0-contract-v06-final.json": "Immutable v06 scientific-baseline contract.",
        "seals/e4-0-contract-v06-seal.json": "Immutable v06 scientific-baseline seal manifest.",
        "contracts/e4-0-contract-v07-final.json": "Immutable v07 historical lineage contract.",
        "seals/e4-0-contract-v07-seal.json": "Immutable v07 historical lineage seal manifest.",
        "audits/e4-0-execution/population-independent-audit-receipt-v01.json": "Independent model-free audit of inherited E4 population; labels unopened.",
        "audits/e4-0-auth-issuer-v02/population-authorization-v01.json": "Historical v06 population-only scoped authorization.",
        "audits/e4-0-auth-issuer-v02/population-bindings-v01.json": "Historical v06 population source/identity bindings.",
        "audits/e4-0-auth-issuer-v02/parity-panel-authorization-v01.json": "Historical v06 tokenizer-only parity-panel authorization.",
        "audits/e4-0-auth-issuer-v02/parity-panel-bindings-v01.json": "Historical v06 tokenizer-only panel selection bindings.",
        "audits/e4-0-auth-issuer-v02/online-parity-authorization-v01.json": "Failed v06 parity authorization; preserved and never reused.",
        "audits/e4-0-auth-issuer-v02/online-parity-bindings-v01.json": "Failed v06 parity stage bindings; preserved as history.",
        "audits/e4-0-track-e/track-e-postseal-receipt-v07.json": "Independent passing audit of immutable v07 contract/seal.",
        "audits/e4-0-auth-issuer-v07/online-parity-precontact-stop-v01.json": "Preserved v07 precontact issuer stop; model/runtime contact did not occur.",
        "audits/e4-0-auth-issuer-v07/online-parity-bindings-v01.json": "Preserved exact attempted v07 authorization bindings.",
        "audits/e4-0-track-e/e4-0-contract-audit-bridge-v02.json": "Preserved v07 audit bridge; not used to authorize execution.",
        "contracts/e4-0-contract-v08-final.json": "Immutable last-sealed v08 predecessor contract.",
        "seals/e4-0-contract-v08-seal.json": "Immutable last-sealed v08 predecessor seal manifest.",
        "audits/e4-0-track-e/track-e-postseal-receipt-v08.json": "Independent passing audit of immutable v08 contract/seal.",
        "audits/e4-0-auth-issuer-v08/online-parity-precontact-stop-v01.json": "Preserved v08 issuer stop; no authorization or model/runtime contact occurred.",
        "audits/e4-0-auth-issuer-v08/online-parity-bindings-v01.json": "Preserved exact attempted v08 authorization bindings.",
        "audits/e4-0-execution/wddm-gpu-lease-preflight-v02.json": "Read-only WDDM pmon process-type snapshot motivating Type-C-only contention classification; no lease/model/runtime contact.",
        "audits/e4-0-track-e/history/E4-0-IMPLEMENTATION-SOURCE-MAP-v07-first-build.md": "Preserved first v08 source-map attempt; not authoritative.",
        "audits/e4-0-track-e/history/E4-0-IMPLEMENTATION-SOURCE-MAP-v07-predecessor-track-audit-stop.md": "Preserved corrected-map attempt associated with the failed independent audit; not authoritative.",
        "audits/e4-0-track-e/history/track-e-preseal-stop-v08-v01.json": "Preserved v08 preseal stop receipt; not authoritative.",
        "audits/e4-0-track-e/history/e4-0-contract-v08-preseal-candidate-v01.json": "Preserved nonauthoritative v08 preseal contract candidate.",
        "contracts/e4-0-contract-v09-final.json": "Preserved v09 contract candidate stopped at independent preseal; no seal exists.",
        "audits/e4-0-track-e/track-e-preseal-receipt-v09.json": "Immutable v09 failed-preseal receipt; not authorization or a seal.",
        "contracts/e4-0-contract-v10-final.json": "Immutable v10 sealed contract; postseal audit member-inventory stop is retained as history.",
        "seals/e4-0-contract-v10-seal.json": "Immutable v10 seal whose root recomputes but member inventory is incomplete per independent audit.",
        "audits/e4-0-track-e/track-e-preseal-receipt-v10.json": "Immutable passing v10 preseal receipt bound to its candidate/map.",
        "audits/e4-0-track-e/track-e-postseal-receipt-v10.json": "Immutable v10 postseal invocation stop; required --seal argument was omitted.",
        "audits/e4-0-track-e/track-e-postseal-receipt-v10-v02.json": "Immutable v10 postseal audit stop identifying missing transitive v07 seal members.",
        "contracts/e4-0-contract-v11-final.json": "Immutable v11 sealed contract; postseal audit found missing transitive v08 members.",
        "seals/e4-0-contract-v11-seal.json": "Immutable v11 seal whose root recomputes but transitive inventory is incomplete per independent audit.",
        "audits/e4-0-track-e/track-e-preseal-receipt-v11.json": "Immutable passing v11 preseal receipt bound to its candidate/map.",
        "audits/e4-0-track-e/track-e-postseal-receipt-v11.json": "Immutable v11 postseal stop identifying missing transitive v08 contract/seal members.",
        "plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v12.md": "Immutable failed v12 source-map build with stale v11 heading/status; preserved without contract binding.",
        "contracts/e4-0-contract-v12-final.json": "Immutable v12 candidate preserved as failed-preseal lineage; no seal exists.",
        "audits/e4-0-track-e/track-e-preseal-receipt-v12.json": "Immutable v12 preseal verifier-schema stop; no authorization or runtime contact occurred.",
        "plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v13.md": "Immutable reviewed v13 map preserved after the v13 finalizer stopped before candidate materialization.",
        "audits/e4-0-track-e/finalization-stop-v13-v01.json": "Exact pre-finalization receipt-status registry stop; no contract candidate or contact occurred.",
        "contracts/e4-0-contract-v14-final.json": "Immutable v14 candidate stopped at independent preseal; no seal exists.",
        "audits/e4-0-track-e/track-e-preseal-receipt-v14.json": "Immutable v14 failed preseal receipt; no authorization or runtime contact occurred.",
        "contracts/e4-0-contract-v15-final.json": "Immutable v15 candidate stopped at independent preseal; no seal exists.",
        "audits/e4-0-track-e/track-e-preseal-receipt-v15.json": "Immutable v15 failed preseal receipt; no authorization or runtime contact occurred.",
        "plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v16.md": "Preserved first v16 source-map candidate; its finalizer stopped on a version-specific receipt source-closure mismatch.",
        "audits/e4-0-track-e/finalization-stop-v16-v01.json": "Exact no-contact record of the first v16 finalizer source-closure stop; no contract or seal was written.",
        "plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v16-v02.md": "Preserved failed v16-v02 source map bound by its preseal stop.",
        "contracts/e4-0-contract-v16-final.json": "Preserved failed v16-v02 candidate contract; its preseal receipt confirms no seal exists.",
        "audits/e4-0-track-e/track-e-preseal-receipt-v16-v02.json": "Exact no-contact v16-v02 preseal stop with the five recorded source/lineage mismatches.",
        "plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v16-v03.md": "Preserved v16-v03 map bound by the exact scope-literal preseal stop.",
        "contracts/e4-0-contract-v16-v02-final.json": "Preserved failed v16-v03 candidate; amendment scope serialization mismatch only, no seal or execution authorization.",
        "audits/e4-0-track-e/track-e-preseal-receipt-v16-v03.json": "Exact no-contact v16-v03 preseal stop recording the single amendment-scope mismatch.",
        "plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v16-v04.md": "Preserved v16-v04 source map bound by the exact failed v16-v04 seal attempt.",
        "contracts/e4-0-contract-v16-v03-final.json": "Preserved v16-v04 preseal-passed candidate; its sealer stopped before manifest creation.",
        "audits/e4-0-track-e/track-e-preseal-receipt-v16-v04.json": "Passing preseal audit for the preserved v16-v04 candidate; included only as failed-seal history.",
        "source/scripts/seal_e4_0_contract_v16_v04.py": "Exact sealer source for the preserved v16-v04 duplicate-member stop.",
        "audits/e4-0-track-e/contract-seal-stop-v16-v04-v01.json": "Exact no-contact record of the v16-v04 duplicate source/input member stop; no seal was written.",
        "contracts/e4-0-contract-v16-v04-final.json": "Exact sealed predecessor whose v16-v04 parity authorization stopped before grant creation.",
        "seals/e4-0-contract-v16-v04-seal.json": "Exact v16-v04 contract seal bound by the preserved parity authorization stop.",
        "audits/e4-0-auth-issuer-v16-v04/online-parity-bindings-v01.json": "Exact v16-v04 parity authorization bindings preserved for the no-contact verifier stop.",
        "audits/e4-0-auth-issuer-v16-v04/online-parity-precontact-stop-v01.json": "Exact no-contact v16-v04 parity authorization stop; no grant, tokenizer/model/CUDA, lease, cache, or label access occurred.",
        "contracts/e4-0-contract-v16-v05-final.json": "Exact sealed v16-v05 contract whose online-parity authorization attempt stopped before grant creation.",
        "seals/e4-0-contract-v16-v05-seal.json": "Exact v16-v05 contract seal bound by the preserved parity authorization stop.",
        "audits/e4-0-track-e/track-e-postseal-receipt-v16-v06.json": "Independent postseal audit of v16-v05 contract and seal.",
        "audits/e4-0-auth-issuer-v16-v05/online-parity-bindings-v01.json": "Exact v16-v05 parity authorization bindings preserved for the no-contact identity-index mismatch.",
        "audits/e4-0-auth-issuer-v16-v05/online-parity-precontact-stop-v01.json": "Exact no-contact v16-v05 parity authorization stop; no grant or runtime/model contact occurred.",
        "plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v16-v08.md": "Preserved failed v16-v08 map candidate bound by its preseal stop.",
        "contracts/e4-0-contract-v16-v06-final.json": "Preserved v16-v08 contract candidate stopped by independent preseal; no contract seal exists.",
        "audits/e4-0-track-e/track-e-preseal-receipt-v16-v08.json": "Exact independent v16-v08 preseal stop receipt with six verifier mismatches.",
        "plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v16-v07.md": "Preserved unsealed v16-v07 map attempt; finalizer stopped before contract candidate creation.",
        "audits/e4-0-track-e/finalization-stop-v16-v07-v01.json": "Exact no-contact finalizer receipt-source-closure stop for the preserved v16-v07 map attempt.",
        "source/history/finalize_e4_0_contract_v16_v08-attempt-v01.py": "Exact finalizer source bytes that produced the preserved v16-v07 map finalization stop.",
        "audits/e4-0-track-e/history/v16-v08-preseal-stop-preservation-v01.json": "Exact append-only preservation receipt for the v16-v08 failed preseal attempt.",
        "plans/history/E4-0-IMPLEMENTATION-SOURCE-MAP-v16-v06-attempt-v01.md": "Preserved first generated v16-v06 map draft with inherited v16-v05 title; superseded before contract finalization and contains no authorization or model contact.",
        "source/scripts/finalize_e4_0_contract_v13.py": "Preserved v13 finalizer source identity associated with the pre-finalization status-registry stop.",
    }
    failed_map = PROJECT / "plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v12.md"
    if digest(failed_map) != (V12_FAILED_MAP_BYTES, V12_FAILED_MAP_SHA256):
        raise RuntimeError("preserved failed v12 generated source-map identity changed")
    for rel, role in inputs.items():
        path = PROJECT / rel
        if not path.is_file():
            raise RuntimeError(f"required historical execution input missing: {path}")
        rows[project_rel(path)] = (path, role)
    preserved_v16_v06_map = WORKSPACE / V16_V06_MAP_ATTEMPT["path"]
    if digest(preserved_v16_v06_map) != (V16_V06_MAP_ATTEMPT["bytes"], V16_V06_MAP_ATTEMPT["sha256"]):
        raise RuntimeError("preserved first v16-v06 generated map identity changed")

    v16_v07_map = WORKSPACE / V16_V07_MAP_ATTEMPT["path"]
    v16_v07_stop = WORKSPACE / V16_V07_FINALIZATION_STOP["path"]
    v16_v07_finalizer_source = WORKSPACE / V16_V07_FINALIZER_ATTEMPT_SOURCE["path"]
    for identity, path in (
        (V16_V07_MAP_ATTEMPT, v16_v07_map),
        (V16_V07_FINALIZATION_STOP, v16_v07_stop),
        (V16_V07_FINALIZER_ATTEMPT_SOURCE, v16_v07_finalizer_source),
    ):
        if digest(path) != (identity["bytes"], identity["sha256"]):
            raise RuntimeError(f"preserved v16-v07 finalization attempt identity changed: {path}")
    failed_attempt = json.loads(v16_v07_stop.read_text(encoding="utf-8"))
    if (failed_attempt.get("status") != V16_V07_FINALIZATION_STOP["status"]
            or failed_attempt.get("stop_class") != "FINALIZER_RECEIPT_SOURCE_CLOSURE_REGISTRY_MISMATCH"
            or failed_attempt.get("source_map") != V16_V07_MAP_ATTEMPT
            or failed_attempt.get("finalizer_source") != V16_V07_FINALIZER_ATTEMPT_SOURCE
            or failed_attempt.get("contract_candidate_written") is not False
            or failed_attempt.get("seal_written") is not False
            or any(failed_attempt.get(key) is not False for key in (
                "authorization_written", "tokenizer_contact", "model_contact", "cuda_initialized",
                "gpu_lease_acquired", "feature_cache_created", "labels_opened",
                "population_truth_files_opened", "template_or_joint_truth_opened"))):
        raise RuntimeError("preserved v16-v07 finalization stop is not the exact no-contact closure mismatch")

    for rel, size, sha in (
        (V16_V03_MAP_REL, V16_V03_MAP_BYTES, V16_V03_MAP_SHA256),
        (V16_V03_CONTRACT_REL, V16_V03_CONTRACT_BYTES, V16_V03_CONTRACT_SHA256),
        (V16_V03_PRESEAL_REL, V16_V03_PRESEAL_BYTES, V16_V03_PRESEAL_SHA256),
    ):
        path = WORKSPACE / rel
        if digest(path) != (size, sha):
            raise RuntimeError(f"preserved v16-v03 failed-preseal artifact identity changed: {rel}")

    for rel, size, sha in (
        (V16_V04_MAP_REL, V16_V04_MAP_BYTES, V16_V04_MAP_SHA256),
        (V16_V04_CONTRACT_REL, V16_V04_CONTRACT_BYTES, V16_V04_CONTRACT_SHA256),
        (V16_V04_PRESEAL_REL, V16_V04_PRESEAL_BYTES, V16_V04_PRESEAL_SHA256),
        (V16_V04_SEALER_REL, V16_V04_SEALER_BYTES, V16_V04_SEALER_SHA256),
        (V16_V04_SEAL_STOP_REL, V16_V04_SEAL_STOP_BYTES, V16_V04_SEAL_STOP_SHA256),
    ):
        if digest(WORKSPACE / rel) != (size, sha):
            raise RuntimeError(f"preserved v16-v04 failed-seal artifact identity changed: {rel}")
    failed_contract = json.loads((WORKSPACE / V16_V04_CONTRACT_REL).read_text(encoding="utf-8"))
    seal_stop = json.loads((WORKSPACE / V16_V04_SEAL_STOP_REL).read_text(encoding="utf-8"))
    if (failed_contract.get("contract_id") != "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V16"
            or failed_contract.get("status") != "SEALED"
            or seal_stop.get("status") != V16_V04_SEAL_STOP_STATUS or seal_stop.get("mode") != "SEAL"
            or seal_stop.get("pass") is not False
            or seal_stop.get("diagnostic", {}).get("message") != V16_V04_SEAL_STOP_DIAGNOSTIC
            or seal_stop.get("contract") != {"path": V16_V04_CONTRACT_REL, "bytes": V16_V04_CONTRACT_BYTES, "sha256": V16_V04_CONTRACT_SHA256}
            or seal_stop.get("source_map") != {"path": V16_V04_MAP_REL, "bytes": V16_V04_MAP_BYTES, "sha256": V16_V04_MAP_SHA256}
            or seal_stop.get("preseal_receipt") != {"path": V16_V04_PRESEAL_REL, "bytes": V16_V04_PRESEAL_BYTES, "sha256": V16_V04_PRESEAL_SHA256}
            or seal_stop.get("sealer_source") != {"path": V16_V04_SEALER_REL, "bytes": V16_V04_SEALER_BYTES, "sha256": V16_V04_SEALER_SHA256}
            or seal_stop.get("final_seal") is not None
            or any(seal_stop.get(key) is not False for key in (
                "authorization_written", "model_contact", "tokenizer_contact", "cuda_initialized",
                "gpu_lease_acquired", "feature_cache_created", "labels_opened",
                "population_truth_files_opened", "template_or_joint_truth_opened"))):
        raise RuntimeError("preserved v16-v04 sealer stop is not the exact duplicate-member no-contact receipt")
    if (PROJECT / "seals/e4-0-contract-v16-v03-seal.json").exists():
        raise RuntimeError("failed v16-v04 candidate unexpectedly has a contract seal")

    auth_bindings_path = PROJECT / V16_V04_AUTH_BINDINGS["path"].removeprefix(
        "experiments/fas-frozen-observer-bundle-engineering-v01/"
    )
    auth_contract_path = PROJECT / "contracts/e4-0-contract-v16-v04-final.json"
    auth_seal_path = PROJECT / "seals/e4-0-contract-v16-v04-seal.json"
    auth_stop_path = PROJECT / V16_V04_AUTH_STOP["path"].removeprefix(
        "experiments/fas-frozen-observer-bundle-engineering-v01/"
    )
    for path, expected in (
        (auth_bindings_path, (V16_V04_AUTH_BINDINGS["bytes"], V16_V04_AUTH_BINDINGS["sha256"])),
        (auth_contract_path, (V16_V04_AUTH_CONTRACT["bytes"], V16_V04_AUTH_CONTRACT["sha256"])),
        (auth_seal_path, (V16_V04_AUTH_SEAL["bytes"], V16_V04_AUTH_SEAL["sha256"])),
        (auth_stop_path, (V16_V04_AUTH_STOP["bytes"], V16_V04_AUTH_STOP["sha256"])),
    ):
        if digest(path) != expected:
            raise RuntimeError(f"preserved v16-v04 authorization-stop artifact identity changed: {path}")
    auth_contract = json.loads(auth_contract_path.read_text(encoding="utf-8"))
    auth_seal = json.loads(auth_seal_path.read_text(encoding="utf-8"))
    auth_stop = json.loads(auth_stop_path.read_text(encoding="utf-8"))
    if (auth_contract.get("status") != "SEALED"
            or auth_seal.get("status") != "SEALED"
            or auth_seal.get("seal_id") != "FAS_E4_0_CONTRACT_V16_V04_SEAL"
            or auth_seal.get("root_sha256") != V16_V04_AUTH_SEAL["root_sha256"]
            or auth_stop.get("status") != V16_V04_AUTH_STOP["status"]
            or auth_stop.get("stop_class") != "AUTHORIZER_CONTRACT_PREDECESSOR_SCHEMA_MISMATCH"
            or auth_stop.get("stage") != "ONLINE_CACHE_PARITY"
            or auth_stop.get("bindings") != V16_V04_AUTH_BINDINGS
            or auth_stop.get("contract") != V16_V04_AUTH_CONTRACT
            or auth_stop.get("contract_seal") != V16_V04_AUTH_SEAL
            or auth_stop.get("diagnostic") != V16_V04_AUTH_DIAGNOSTIC
            or auth_stop.get("authorization_output") != V16_V04_AUTH_OUTPUT
            or any(auth_stop.get(key) is not False for key in (
                "authorization_written", "tokenizer_contact", "model_contact", "cuda_initialized",
                "gpu_lease_acquired", "feature_cache_created", "labels_opened",
                "population_truth_files_opened", "template_or_joint_truth_opened"))):
        raise RuntimeError("preserved v16-v04 authorizer stop differs from exact pre-contact failure")
    if (PROJECT / V16_V04_AUTH_OUTPUT["path"].removeprefix(
            "experiments/fas-frozen-observer-bundle-engineering-v01/")).exists():
        raise RuntimeError("failed v16-v04 authorization unexpectedly emitted a grant")

    v16_v05_auth_paths = (
        (V16_V05_AUTH_BINDINGS, "attempted bindings"),
        (V16_V05_AUTH_CONTRACT, "sealed contract"),
        (V16_V05_AUTH_SEAL, "sealed manifest"),
        (V16_V05_AUTH_STOP, "pre-contact stop"),
    )
    for identity, label in v16_v05_auth_paths:
        path = PROJECT / identity["path"].removeprefix(
            "experiments/fas-frozen-observer-bundle-engineering-v01/"
        )
        if digest(path) != (identity["bytes"], identity["sha256"]):
            raise RuntimeError(f"preserved v16-v05 authorization {label} identity changed: {path}")
    v16_v05_contract = json.loads((PROJECT / "contracts/e4-0-contract-v16-v05-final.json").read_text(encoding="utf-8"))
    v16_v05_seal = json.loads((PROJECT / "seals/e4-0-contract-v16-v05-seal.json").read_text(encoding="utf-8"))
    v16_v05_stop_path = PROJECT / V16_V05_AUTH_STOP["path"].removeprefix(
        "experiments/fas-frozen-observer-bundle-engineering-v01/"
    )
    v16_v05_stop = json.loads(v16_v05_stop_path.read_text(encoding="utf-8"))
    if (v16_v05_contract.get("status") != "SEALED"
            or v16_v05_seal.get("status") != "SEALED"
            or v16_v05_seal.get("seal_id") != "FAS_E4_0_CONTRACT_V16_V05_SEAL"
            or v16_v05_seal.get("root_sha256") != V16_V05_AUTH_SEAL["root_sha256"]
            or v16_v05_stop.get("status") != "PRECONTACT_STOP"
            or v16_v05_stop.get("stop_class") != "AUTHORIZER_REFERENCE_AUTHORIZATION_ID_MISMATCH"
            or v16_v05_stop.get("stage") != "ONLINE_CACHE_PARITY"
            or v16_v05_stop.get("bindings") != V16_V05_AUTH_BINDINGS
            or v16_v05_stop.get("contract") != V16_V05_AUTH_CONTRACT
            or v16_v05_stop.get("contract_seal") != V16_V05_AUTH_SEAL
            or v16_v05_stop.get("diagnostic") != V16_V05_AUTH_DIAGNOSTIC
            or v16_v05_stop.get("authorization_output") != V16_V05_AUTH_OUTPUT
            or any(v16_v05_stop.get(key) is not False for key in (
                "authorization_written", "tokenizer_contact", "model_contact", "cuda_initialized",
                "gpu_lease_acquired", "feature_cache_created", "labels_opened",
                "population_truth_files_opened", "template_or_joint_truth_opened"))):
        raise RuntimeError("preserved v16-v05 authorization stop differs from exact no-contact identity-index failure")
    if (PROJECT / V16_V05_AUTH_OUTPUT["path"].removeprefix(
            "experiments/fas-frozen-observer-bundle-engineering-v01/")).exists():
        raise RuntimeError("failed v16-v05 authorization unexpectedly emitted a grant")

    first_v16_map = PROJECT / "plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v16.md"
    first_v16_stop = PROJECT / "audits/e4-0-track-e/finalization-stop-v16-v01.json"
    if digest(first_v16_map) != (V16_FIRST_MAP_BYTES, V16_FIRST_MAP_SHA256):
        raise RuntimeError("preserved first v16 source-map candidate identity changed")
    if digest(first_v16_stop) != (V16_FINALIZATION_STOP_BYTES, V16_FINALIZATION_STOP_SHA256):
        raise RuntimeError("preserved v16 finalizer stop receipt identity changed")
    first_v16_stop_payload = json.loads(first_v16_stop.read_text(encoding="utf-8"))
    if (first_v16_stop_payload.get("status") != V16_FINALIZATION_STOP_STATUS
            or first_v16_stop_payload.get("contract_candidate_written") is not False
            or first_v16_stop_payload.get("seal_written") is not False
            or first_v16_stop_payload.get("model_contact") is not False
            or first_v16_stop_payload.get("tokenizer_contact") is not False
            or first_v16_stop_payload.get("cuda_initialized") is not False
            or first_v16_stop_payload.get("labels_opened") is not False):
        raise RuntimeError("preserved v16 finalizer stop is not the exact no-contact source-closure stop")

    v15_map = PROJECT / "plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v15.md"
    v15_contract = PROJECT / "contracts/e4-0-contract-v15-final.json"
    v15_preseal = PROJECT / "audits/e4-0-track-e/track-e-preseal-receipt-v15.json"
    for path, expected in (
        (v15_map, (V15_MAP_BYTES, V15_MAP_SHA256)),
        (v15_contract, (V15_CONTRACT_BYTES, V15_CONTRACT_SHA256)),
        (v15_preseal, (V15_PRESEAL_BYTES, V15_PRESEAL_SHA256)),
    ):
        if digest(path) != expected:
            raise RuntimeError(f"preserved failed v15 preseal artifact changed: {path}")
    v15_stop = json.loads(v15_preseal.read_text(encoding="utf-8"))
    absent_contact = ("authorization_written", "tokenizer_contact", "model_contact", "cuda_initialized",
                      "gpu_lease_acquired", "feature_cache_created", "labels_opened")
    if (v15_stop.get("status") != V15_PRESEAL_STATUS
            or v15_stop.get("issues") != V15_PRESEAL_ISSUES
            or v15_stop.get("pass") is not False or v15_stop.get("final_seal") is not None
            or v15_stop.get("population_truth_files_opened") is not False
            or v15_stop.get("template_or_joint_truth_opened") is not False
            or any(key in v15_stop for key in absent_contact)):
        raise RuntimeError("preserved v15 preseal stop does not match exact no-contact receipt schema")

    v12_map = PROJECT / "plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v11.md"
    v12_contract = PROJECT / "contracts/e4-0-contract-v12-final.json"
    v12_stop = PROJECT / "audits/e4-0-track-e/track-e-preseal-receipt-v12.json"
    expected_v12 = (
        (v12_map, 91198, "61df89861d9540641305cdb0020a7bc95772a8adab529e5fdd62898e4c066930"),
        (v12_contract, 78271, "9dee0e26b3eb1fcdbcc7146214745f8d699459bfdd23f15b8532e87cc9da3e75"),
        (v12_stop, 111784, "4ac87653ae964e3ede95876ba3a9a7a32402672331d1c25f9b41d06725131f24"),
    )
    for path, expected_size, expected_sha in expected_v12:
        if digest(path) != (expected_size, expected_sha):
            raise RuntimeError(f"preserved failed v12 preseal artifact changed: {path}")
    v12_receipt = json.loads(v12_stop.read_text(encoding="utf-8"))
    if (v12_receipt.get("status") != "E4_0_TRACK_E_PRESEAL_STOP_MISMATCHES_RECORDED_V12"
            or v12_receipt.get("issues") != ["v12 amendment does not preserve v11 lineage or bind the exact v08 inventory repair"]
            or v12_receipt.get("pass") is not False or v12_receipt.get("final_seal") is not None
            or any(v12_receipt.get(key) is not False for key in (
                "population_truth_files_opened", "template_or_joint_truth_opened"))
            or any(v12_receipt.get(key) is not None for key in (
                "authorization_written", "tokenizer_contact", "model_contact", "cuda_initialized",
                "gpu_lease_acquired", "feature_cache_created", "labels_opened"))):
        raise RuntimeError("preserved v12 preseal stop is not exact no-contact auditor-schema evidence")

    v13_map = PROJECT / "plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v13.md"
    v13_finalizer = PROJECT / "source/scripts/finalize_e4_0_contract_v13.py"
    v13_stop = PROJECT / "audits/e4-0-track-e/finalization-stop-v13-v01.json"
    for path, expected_size, expected_sha in (
        (v13_map, V13_DRAFT_MAP_BYTES, V13_DRAFT_MAP_SHA256),
        (v13_finalizer, V13_FINALIZER_BYTES, V13_FINALIZER_SHA256),
        (v13_stop, V13_FINALIZATION_STOP_BYTES, V13_FINALIZATION_STOP_SHA256),
    ):
        if digest(path) != (expected_size, expected_sha):
            raise RuntimeError(f"preserved v13 finalization attempt artifact changed: {path}")
    v13_stop_receipt = json.loads(v13_stop.read_text(encoding="utf-8"))
    expected_diagnostic = "receipt status mismatch or failure: experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/track-e-source-tests-v20.json"
    if (v13_stop_receipt.get("status") != "E4_0_V13_FINALIZATION_STOP_RECEIPT_STATUS_MISMATCH"
            or v13_stop_receipt.get("pass") is not False
            or v13_stop_receipt.get("contract_candidate") is not None
            or v13_stop_receipt.get("final_seal") is not None
            or v13_stop_receipt.get("diagnostic", {}).get("message") != expected_diagnostic
            or any(v13_stop_receipt.get(key) is not False for key in (
                "authorization_written", "model_contact", "tokenizer_contact", "cuda_initialized",
                "gpu_lease_acquired", "feature_cache_created", "labels_opened",
                "population_truth_files_opened", "template_or_joint_truth_opened"))):
        raise RuntimeError("preserved v13 finalization stop is not exact no-contact status-registry evidence")

    v14_map = PROJECT / "plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v14.md"
    v14_contract = PROJECT / "contracts/e4-0-contract-v14-final.json"
    v14_preseal = PROJECT / "audits/e4-0-track-e/track-e-preseal-receipt-v14.json"
    for path, expected_size, expected_sha in (
        (v14_map, V14_MAP_BYTES, V14_MAP_SHA256),
        (v14_contract, V14_CONTRACT_BYTES, V14_CONTRACT_SHA256),
        (v14_preseal, V14_PRESEAL_BYTES, V14_PRESEAL_SHA256),
    ):
        if digest(path) != (expected_size, expected_sha):
            raise RuntimeError(f"preserved failed v14 candidate artifact changed: {path}")
    v14_stop = json.loads(v14_preseal.read_text(encoding="utf-8"))
    validate_v14_preseal_stop(v14_stop)

    v10_preseal = json.loads(v10_preseal_path.read_text(encoding="utf-8"))
    v10_seal = json.loads(v10_seal_path.read_text(encoding="utf-8"))
    if (v10_preseal.get("status") != "E4_0_TRACK_E_PRESEAL_PASS_V10_CONTRACT_AND_SOURCE_MAP_CLOSED"
            or v10_preseal.get("pass") is not True
            or v10_preseal.get("final_seal") is not None
            or v10_seal.get("status") != "SEALED"
            or v10_seal.get("seal_id") != "FAS_E4_0_CONTRACT_V10_SEAL"
            or v10_seal.get("root_sha256") != V10_SEAL_ROOT_SHA256
            or v10_seal.get("entry_count") != 221):
        raise RuntimeError("preserved v10 preseal/seal status or root differs")

    checks = (
        (v10_contract_path, V10_CONTRACT_BYTES, V10_CONTRACT_SHA256),
        (v10_seal_path, V10_SEAL_BYTES, V10_SEAL_SHA256),
        (v10_preseal_path, V10_PRESEAL_BYTES, V10_PRESEAL_SHA256),
        (v10_stop1_path, V10_POSTSEAL_V01_BYTES, V10_POSTSEAL_V01_SHA256),
        (v10_stop2_path, V10_POSTSEAL_V02_BYTES, V10_POSTSEAL_V02_SHA256),
    )
    for path, expected_size, expected_sha in checks:
        actual_size, actual_sha = digest(path)
        if (actual_size, actual_sha) != (expected_size, expected_sha):
            raise RuntimeError(f"preserved v10 lineage artifact changed: {path}")
    v10_stop1 = json.loads(v10_stop1_path.read_text(encoding="utf-8"))
    v10_stop2 = json.loads(v10_stop2_path.read_text(encoding="utf-8"))
    expected_v10_issues = [
        "v10 seal omits required member paths: ['experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v07-final.json', 'experiments/fas-frozen-observer-bundle-engineering-v01/seals/e4-0-contract-v07-seal.json']",
        "v10 seal lacks exact scientific-baseline/immediate-predecessor member: E4_0_CONTRACT_V07_SUPERSEDED",
        "v10 seal lacks exact scientific-baseline/immediate-predecessor member: E4_0_CONTRACT_V07_SEAL_SUPERSEDED",
    ]
    if (v10_stop1.get("status") != "E4_0_TRACK_E_POSTSEAL_STOP_MISMATCHES_RECORDED_V10"
            or v10_stop1.get("pass") is not False
            or v10_stop1.get("issues") != ["postseal mode requires a contract seal"]
            or v10_stop1.get("final_seal") is not None
            or v10_stop2.get("status") != "E4_0_TRACK_E_POSTSEAL_STOP_MISMATCHES_RECORDED_V10"
            or v10_stop2.get("pass") is not False or v10_stop2.get("issues") != expected_v10_issues
            or v10_stop2.get("final_seal", {}).get("root_match") is not True
            or v10_stop2.get("final_seal", {}).get("member_set_exact") is not False):
        raise RuntimeError("preserved v10 postseal attempts do not match the exact seal-member stop history")

    v11_checks = (
        (v11_contract_path, V11_CONTRACT_BYTES, V11_CONTRACT_SHA256),
        (v11_seal_path, V11_SEAL_BYTES, V11_SEAL_SHA256),
        (v11_preseal_path, V11_PRESEAL_BYTES, V11_PRESEAL_SHA256),
        (v11_stop_path, V11_POSTSEAL_BYTES, V11_POSTSEAL_SHA256),
    )
    for path, expected_size, expected_sha in v11_checks:
        actual_size, actual_sha = digest(path)
        if (actual_size, actual_sha) != (expected_size, expected_sha):
            raise RuntimeError(f"preserved v11 lineage artifact changed: {path}")
    v11_contract = json.loads(v11_contract_path.read_text(encoding="utf-8"))
    v11_seal = json.loads(v11_seal_path.read_text(encoding="utf-8"))
    v11_preseal = json.loads(v11_preseal_path.read_text(encoding="utf-8"))
    v11_stop = json.loads(v11_stop_path.read_text(encoding="utf-8"))
    expected_v11_issues = [
        "v11 seal omits required member paths: ['experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v08-final.json', 'experiments/fas-frozen-observer-bundle-engineering-v01/seals/e4-0-contract-v08-seal.json']",
        "v11 seal lacks exact scientific-baseline/immediate-predecessor member: E4_0_CONTRACT_V08_SUPERSEDED",
        "v11 seal lacks exact scientific-baseline/immediate-predecessor member: E4_0_CONTRACT_V08_SEAL_SUPERSEDED",
    ]
    if (v11_contract.get("contract_id") != "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V11"
            or v11_contract.get("status") != "SEALED"
            or v11_seal.get("seal_id") != "FAS_E4_0_CONTRACT_V11_SEAL"
            or v11_seal.get("root_sha256") != V11_SEAL_ROOT_SHA256
            or v11_preseal.get("status") != "E4_0_TRACK_E_PRESEAL_PASS_V11_CONTRACT_AND_SOURCE_MAP_CLOSED"
            or v11_preseal.get("pass") is not True
            or v11_stop.get("status") != "E4_0_TRACK_E_POSTSEAL_STOP_MISMATCHES_RECORDED_V11"
            or v11_stop.get("pass") is not False
            or v11_stop.get("issues") != expected_v11_issues
            or v11_stop.get("final_seal", {}).get("root_match") is not True
            or v11_stop.get("final_seal", {}).get("member_set_exact") is not False
            or v11_stop.get("final_seal", {}).get("entry_count") != 238
            or v11_stop.get("final_seal", {}).get("expected_member_count") != 240):
        raise RuntimeError("preserved v11 postseal attempt differs from the exact missing-v08-member stop")

    wddm_path = PROJECT / "audits/e4-0-execution/wddm-gpu-lease-preflight-v02.json"
    wddm_size, wddm_sha = digest(wddm_path)
    wddm = json.loads(wddm_path.read_text(encoding="utf-8"))
    if (wddm_size != WDDM_PREFLIGHT_BYTES or wddm_sha != WDDM_PREFLIGHT_SHA256
            or wddm.get("total_gpu_memory_claimed") is not False
            or wddm.get("gpu_lease_acquired") is not False
            or wddm.get("model_contact") is not False
            or wddm.get("tokenizer_contact") is not False
            or wddm.get("cuda_initialized_by_this_task") is not False
            or wddm.get("feature_cache_created") is not False
            or wddm.get("labels_opened") is not False):
        raise RuntimeError("WDDM preflight diagnostic identity or no-contact flags differ")

    historical = (
        ("audits/e4-0-track-e/history/E4-0-IMPLEMENTATION-SOURCE-MAP-v07-first-build.md", V08_FIRST_MAP_BYTES, V08_FIRST_MAP_SHA256),
        ("audits/e4-0-track-e/history/E4-0-IMPLEMENTATION-SOURCE-MAP-v07-predecessor-track-audit-stop.md", V08_AUDIT_STOP_MAP_BYTES, V08_AUDIT_STOP_MAP_SHA256),
        ("audits/e4-0-track-e/history/track-e-preseal-stop-v08-v01.json", V08_PRESEAL_STOP_BYTES, V08_PRESEAL_STOP_SHA256),
        ("audits/e4-0-track-e/history/e4-0-contract-v08-preseal-candidate-v01.json", V08_PRESEAL_CANDIDATE_BYTES, V08_PRESEAL_CANDIDATE_SHA256),
    )
    for rel, expected_bytes, expected_sha in historical:
        path = PROJECT / Path(rel)
        size, sha = digest(path)
        if size != expected_bytes or sha != expected_sha:
            raise RuntimeError(f"preserved v08 preseal-history identity changed: {rel}")
    preseal_stop = json.loads((PROJECT / "audits/e4-0-track-e/history/track-e-preseal-stop-v08-v01.json").read_text(encoding="utf-8"))
    if preseal_stop.get("status") != "E4_0_TRACK_E_PRESEAL_STOP_MISMATCHES_RECORDED_V08":
        raise RuntimeError("preserved v08 preseal stop status differs")

    v08_contract = PROJECT / "contracts" / "e4-0-contract-v08-final.json"
    v08_seal = PROJECT / "seals" / "e4-0-contract-v08-seal.json"
    v08_audit = PROJECT / "audits" / "e4-0-track-e" / "track-e-postseal-receipt-v08.json"
    contract_size, contract_sha = digest(v08_contract)
    seal_size, seal_sha = digest(v08_seal)
    audit_size, audit_sha = digest(v08_audit)
    if (contract_size != V08_CONTRACT_BYTES or contract_sha != V08_CONTRACT_SHA256
            or seal_size != V08_SEAL_BYTES or seal_sha != V08_SEAL_SHA256
            or audit_size != 68220 or audit_sha != V08_POSTSEAL_AUDIT_SHA256):
        raise RuntimeError("preserved v08 predecessor contract, seal, or audit identity changed")
    contract_payload = json.loads(v08_contract.read_text(encoding="utf-8"))
    seal_payload = json.loads(v08_seal.read_text(encoding="utf-8"))
    audit_payload = json.loads(v08_audit.read_text(encoding="utf-8"))
    if (contract_payload.get("contract_id") != "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V08"
            or contract_payload.get("status") != "SEALED"
            or seal_payload.get("seal_id") != "FAS_E4_0_CONTRACT_V08_SEAL"
            or seal_payload.get("root_sha256") != V08_ROOT_SHA256
            or audit_payload.get("pass") is not True
            or "PASS" not in str(audit_payload.get("status", "")).upper()
            or audit_payload.get("final_seal", {}).get("root_sha256") != V08_ROOT_SHA256):
        raise RuntimeError("preserved v08 predecessor status or independent audit is invalid")
    bindings_path = PROJECT / "audits/e4-0-auth-issuer-v08/online-parity-bindings-v01.json"
    stop_path = PROJECT / "audits/e4-0-auth-issuer-v08/online-parity-precontact-stop-v01.json"
    bindings_size, bindings_sha = digest(bindings_path)
    stop_size, stop_sha = digest(stop_path)
    if (bindings_size != V08_AUTH_BINDINGS_BYTES or bindings_sha != V08_AUTH_BINDINGS_SHA256
            or stop_size != V08_AUTH_STOP_BYTES or stop_sha != V08_AUTH_STOP_SHA256):
        raise RuntimeError("preserved v08 authorization attempt identity changed")
    stop_payload = json.loads(stop_path.read_text(encoding="utf-8"))
    validate_v08_authorization_stop(stop_payload)

    population_audit = PROJECT / "audits" / "e4-0-execution" / "population-independent-audit-receipt-v01.json"
    audit_size, audit_sha = digest(population_audit)
    audit = json.loads(population_audit.read_text(encoding="utf-8"))
    if (audit_size != 858 or audit_sha != POPULATION_AUDIT_SHA256
            or audit.get("status") != "PASS_POPULATION_FRESHNESS_SUPPORT"
            or audit.get("population_root_sha256") != POPULATION_ROOT_SHA256
            or audit.get("all_checks_passed") is not True
            or audit.get("population_truth_files_opened") is not False
            or audit.get("primary_support", {}).get("heldout_or_joint_support_read") is not False):
        raise RuntimeError("inherited population audit is not a model-free truth-closed pass")

    runtime_inputs = (
        (RUN_ROOT / "stage-seal-v01.json", "Inherited v06 population stage seal; root is immutable.", "population stage seal"),
        (RUN_ROOT / "parity-panel" / "stage-seal-v01.json", "Inherited v06 tokenizer-only parity-panel seal; root is immutable.", "parity panel stage seal"),
        (RUN_ROOT / "parity-panel" / "selection-receipt-v01.json", "Inherited label-free tokenizer-only panel selection receipt.", "parity panel receipt"),
    )
    panel_auth_path = PROJECT / "audits" / "e4-0-auth-issuer-v02" / "parity-panel-authorization-v01.json"
    parity_auth_path = PROJECT / "audits" / "e4-0-auth-issuer-v02" / "online-parity-authorization-v01.json"
    panel_auth = json.loads(panel_auth_path.read_text(encoding="utf-8"))
    parity_auth = json.loads(parity_auth_path.read_text(encoding="utf-8"))
    audit_auth_size, audit_auth_sha = digest(population_audit)
    for auth in (panel_auth, parity_auth):
        entry = auth.get("artifacts", {}).get("population_audit")
        if not isinstance(entry, dict) or (
            Path(str(entry.get("path", ""))).resolve() != population_audit.resolve()
            or entry.get("sha256") != audit_auth_sha or entry.get("bytes") != audit_auth_size
        ):
            raise RuntimeError("inherited population audit differs from its preserved v06 authorization")
    auth_bindings = {
        "population stage seal": ((panel_auth, "population_seal"), (parity_auth, "population_seal")),
        "parity panel stage seal": ((parity_auth, "parity_panel_seal"),),
    }
    for path, role, label in runtime_inputs:
        if not path.is_file():
            raise RuntimeError(f"required inherited runtime artifact missing ({label}): {path}")
        size, sha = digest(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        for auth, artifact_name in auth_bindings.get(label, ()):
            entry = auth.get("artifacts", {}).get(artifact_name)
            if not isinstance(entry, dict):
                raise RuntimeError(f"preserved v06 authorization omits the inherited artifact: {artifact_name}")
            bound_path = Path(str(entry.get("path", "")))
            if (not bound_path.is_absolute() or bound_path.resolve() != path.resolve()
                    or entry.get("sha256") != sha or entry.get("bytes") != size):
                raise RuntimeError(f"inherited artifact differs from its preserved v06 authorization: {label}")
        if label != "parity panel receipt" and payload.get("status") != "SEALED":
            raise RuntimeError(f"inherited artifact is not sealed ({label})")
        if label == "population stage seal" and (
            payload.get("stage") != "POPULATION_GENERATION"
            or payload.get("root_sha256") != POPULATION_ROOT_SHA256
            or payload.get("contract_seal_root_sha256") != V06_ROOT_SHA256
            or any(payload.get("exact_predecessor_roots", {}).get(key) != value for key, value in {
                "e0_v10_root_sha256": "899a131c09298fdafdcc6771ad01e8982857a1cd47900259800f97dd7bea7ccd",
                "e1_v04_root_sha256": "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03",
                "e2_v07_root_sha256": "a2e2aa76f77904665b9abfa2a22f609c05219d8bc64c537bed41f5c634d1da8a",
                "e3_v02_bundle_root_sha256": "899ff6a61272b86fdf1cd51d8c14100e77185157c242f27fbffe452803a435e1",
            }.items())
        ):
            raise RuntimeError("inherited population seal identity differs from frozen v06 roots")
        if label == "parity panel stage seal" and (
            payload.get("stage") != "PARITY_PANEL_MATERIALIZATION"
            or payload.get("root_sha256") != PANEL_ROOT_SHA256
            or payload.get("contract_seal_root_sha256") != V06_ROOT_SHA256
            or payload.get("exact_predecessor_roots", {}).get("e4_population_root_sha256") != POPULATION_ROOT_SHA256
            or payload.get("exact_predecessor_roots", {}).get("e4_population_audit_root_sha256") != POPULATION_AUDIT_SHA256
        ):
            raise RuntimeError("inherited parity-panel seal identity differs from frozen v06 roots")
        if label == "parity panel receipt" and (
            payload.get("status") != "PARITY_PANEL_SEALED"
            or payload.get("e4_contract_root_sha256") != V06_ROOT_SHA256
            or payload.get("authorization_sha256") != PANEL_AUTHORIZATION_SHA256
            or payload.get("labels_opened") is not False
            or payload.get("predictions_emitted") is not False
            or payload.get("model_contact_performed") is not False
            or payload.get("model_loaded") is not False
            or payload.get("cuda_initialized") is not False
            or payload.get("tokenizer_contact_performed") is not True
            or payload.get("tokenizer_loaded") is not True
        ):
            raise RuntimeError("inherited parity panel is not the exact label-free tokenizer-only v06 selection")
        rows[canonical_key(path)] = (path, role + f" SHA-256={sha}, bytes={size}")

    return [(rel, path, role) for rel, (path, role) in sorted(rows.items(), key=lambda item: item[0].encode("utf-8"))]


REISSUED_RECEIPT_PATHS = {
    "audits/e4-0-track-e/track-e-source-tests-v25.json",
    "audits/e4-0-track-e/track-e-source-tests-v27.json",
    "audits/e4-0-auth-issuer-v15/source-tests-v01.json",
    "audits/e4-0-auth-issuer-v15/source-tests-v02.json",
    "audits/e4-0-track-e/contract-tooling-source-tests-v15.json",
    "audits/e4-0-track-e/contract-tooling-source-tests-v15-v02.json",
    "audits/e4-0-track-e/contract-tooling-source-tests-v15-v03.json",
}

CURRENT_RECEIPTS = (
    ("Predecessor Track E v15 pre-map attempt 1", "audits/e4-0-track-e/track-e-source-tests-v25.json"),
    ("Predecessor Track E v15 pre-map attempt 2", "audits/e4-0-track-e/track-e-source-tests-v27.json"),
    ("Initial Authorization issuer v15", "audits/e4-0-auth-issuer-v15/source-tests-v01.json"),
    ("Authorization issuer v15", "audits/e4-0-auth-issuer-v15/source-tests-v02.json"),
    ("Initial Contract tooling v15", "audits/e4-0-track-e/contract-tooling-source-tests-v15.json"),
    ("Predecessor Contract tooling v15 v02", "audits/e4-0-track-e/contract-tooling-source-tests-v15-v02.json"),
    ("Contract tooling v15", "audits/e4-0-track-e/contract-tooling-source-tests-v15-v03.json"),
    ("Initial Track E v16 pre-map", "audits/e4-0-track-e/track-e-source-tests-v28.json"),
    ("Predecessor Track E v16 pre-map v02", "audits/e4-0-track-e/track-e-source-tests-v29.json"),
    ("Track E v16 pre-map", "audits/e4-0-track-e/track-e-source-tests-v30.json"),
    ("Authorization issuer v16", "audits/e4-0-auth-issuer-v16/source-tests-v01.json"),
    ("Authorization issuer v16 v02", "audits/e4-0-auth-issuer-v16-v02/source-tests-v01.json"),
    ("Initial Contract tooling v16", "audits/e4-0-track-e/contract-tooling-source-tests-v16.json"),
    ("Predecessor Contract tooling v16 v02", "audits/e4-0-track-e/contract-tooling-source-tests-v16-v02.json"),
    ("Contract tooling v16", "audits/e4-0-track-e/contract-tooling-source-tests-v16-v03.json"),
    ("Track E v16 pre-map v04 v02", "audits/e4-0-track-e/track-e-source-tests-v31-v02.json"),
    ("Contract tooling v16 v04 v02", "audits/e4-0-track-e/contract-tooling-source-tests-v16-v04-v02.json"),
    ("Track E v16 pre-map v05", "audits/e4-0-track-e/track-e-source-tests-v32.json"),
    ("Authorization issuer v16 v03", "audits/e4-0-auth-issuer-v16-v03/source-tests-v01.json"),
    ("Contract tooling v16 v05", "audits/e4-0-track-e/contract-tooling-source-tests-v16-v05.json"),
    ("Track E v16 pre-map v06", "audits/e4-0-track-e/track-e-source-tests-v33.json"),
    ("Authorization issuer v16 v04", "audits/e4-0-auth-issuer-v16-v04/source-tests-v01.json"),
    ("Contract tooling v16 v06", "audits/e4-0-track-e/contract-tooling-source-tests-v16-v06.json"),
    ("Track E v16 pre-map v07", "audits/e4-0-track-e/track-e-source-tests-v34.json"),
    ("Authorization issuer v16 v05", "audits/e4-0-auth-issuer-v16-v05/source-tests-v01.json"),
    ("Contract tooling v16 v07", "audits/e4-0-track-e/contract-tooling-source-tests-v16-v07.json"),
    ("Authorization issuer v16 v06", "audits/e4-0-auth-issuer-v16-v06/source-tests-v01.json"),
    ("Contract tooling v16 v08", "audits/e4-0-track-e/contract-tooling-source-tests-v16-v08.json"),
    ("Track E v16 pre-map v08", "audits/e4-0-track-e/track-e-source-tests-v35.json"),
    ("Contract tooling v16 v09", "audits/e4-0-track-e/contract-tooling-source-tests-v16-v09.json"),
    ("Track E v16 pre-map v09", "audits/e4-0-track-e/track-e-source-tests-v36.json"),
)


def collect_receipts() -> list[tuple[str, str, Path, str]]:
    prior = []
    current_paths = {rel for _track, rel in CURRENT_RECEIPTS}
    for track, path_text, size_text, sha, status in table(PRIOR_MAP, ["Track", "Path", "Bytes", "SHA-256", "Status"]):
        verify_row(path_text, size_text, sha)
        normalized_path = path_text
        project_prefix = f"{PROJECT.relative_to(WORKSPACE).as_posix()}/"
        if normalized_path.startswith(project_prefix):
            normalized_path = normalized_path[len(project_prefix):]
        if normalized_path in REISSUED_RECEIPT_PATHS or normalized_path in current_paths:
            continue
        prior.append((predecessor_track(track), path_text, resolve_bound(path_text), status))

    result = prior
    seen_paths: set[str] = set()
    seen_tracks: set[str] = set()
    for track, rel, path, status in prior:
        key = canonical_key(path)
        if key in seen_paths or track in seen_tracks:
            raise RuntimeError(f"duplicate predecessor receipt path or track: {track}: {rel}")
        if status not in PASS_STATUSES:
            raise RuntimeError(f"predecessor receipt status is not an exact accepted status: {track}: {status}")
        seen_paths.add(key)
        seen_tracks.add(track)
    for track, rel in CURRENT_RECEIPTS:
        path = PROJECT / rel
        if not path.is_file():
            raise RuntimeError(f"required passing source/test receipt missing for {track}: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        status = str(payload.get("status", ""))
        if status != CURRENT_RECEIPT_STATUSES.get(track):
            raise RuntimeError(f"source/test receipt has an unregistered status for {track}: {status}")
        key = canonical_key(path)
        if key in seen_paths or track in seen_tracks:
            raise RuntimeError(f"duplicate source/test receipt path or track: {track}: {rel}")
        seen_paths.add(key)
        seen_tracks.add(track)
        if track == "Initial Track E v15 pre-map":
            if digest(path) != (V15_TRACK_E_V01_BYTES, V15_TRACK_E_V01_SHA256):
                raise RuntimeError("preserved initial v15 Track E receipt identity changed")
        elif track == "Initial Contract tooling v15":
            if digest(path) != (V15_TOOLING_V01_BYTES, V15_TOOLING_V01_SHA256):
                raise RuntimeError("preserved initial v15 tooling receipt identity changed")
        elif track == "Initial Authorization issuer v15":
            if digest(path) != (V15_ISSUER_V01_BYTES, V15_ISSUER_V01_SHA256):
                raise RuntimeError("preserved initial v15 issuer receipt identity changed")
        elif track == "Predecessor Contract tooling v15 v02":
            if digest(path) != (V15_TOOLING_V02_BYTES, V15_TOOLING_V02_SHA256):
                raise RuntimeError("preserved v02 v15 tooling receipt identity changed")
        else:
            verify_receipt_source_bindings(track, payload, collect_sources())
        result.append((track, project_rel(path), path, status))
    return result


def predecessor_track(track: str) -> str:
    return track if track.startswith("Predecessor ") else "Predecessor " + track


def main() -> int:
    if OUTPUT.exists():
        raise RuntimeError(f"refusing to overwrite immutable v16-v09 source map: {OUTPUT}")
    source_rows = collect_sources()
    input_rows = collect_inputs()
    receipt_rows = collect_receipts()

    def source_line(rel: str, path: Path, role: str) -> str:
        size, sha = digest(path)
        return f"| `{rel}` | {size} | `{sha}` | {role} |"

    def receipt_line(track: str, rel: str, path: Path, status: str) -> str:
        size, sha = digest(path)
        return f"| {track} | `{rel}` | {size} | `{sha}` | `{status}` |"

    content = [
        "# E4-0 Implementation Source Map v16-v09",
        "",
        "Status: v16-v09 tooling successor preserves the failed v16-v08 candidate, map, and preseal stop; it repairs only independent source-role projections and historical field-shape expectations. Scientific fields and E4-0 execution boundaries remain unchanged. No model contact, scoring, or stage authorization is granted.",
        "",
        "## Frozen semantic baseline",
        "",
        "- Immutable scientific baseline: `contracts/e4-0-contract-v06-final.json`; v16 supersedes the sealed v11 contract and preserves exact science equality to v06.",
        "- Sealed v06 contract root: `7344badf07476d19d9c6228f80d026a112c339e93daa75593e61031f68456e64`; v06 contract SHA-256: `ea4f11cec5d65a3be7716c77febf5d448d8ebf1a5a4049aee5d25d51c0c50958`.",
        "- E0 v10, E1 v04, E2 v07, and E3 v02 roots and every population, parity, truth, resource, and simultaneous-scoring gate remain unchanged.",
        "- Inherited population root: `27731b483b8242aaef15ca22b97796b7b305a79db9bbb235765e13dcd9d08967`; independent population audit remains truth-closed.",
        "- Inherited tokenizer-only parity-panel root: `6ef00306df0df20ada7b7a86b09567ae46e07f112f66d974d7885e8f1e5d4d95`; the failed v06 online-parity attempt remains a pre-contact stop and is never reused.",
        "- v08 authorization stopped before authorization write or model/runtime contact because the issuer expected a top-level population-audit field; its exact contract, seal, postseal audit, stop, and bindings remain sealed lineage.",
        "- v09 stopped before seal; v10 and v11 sealed with valid roots but incomplete transitive member inventories. The exact v10 and v11 independent postseal stops remain bound as history.",
        "- The v16-v09 independent Track E auditor checks the complete v06-v11 sealed-ancestor closure, exact failed v12-v15/v16 lineage, failed v16-v04 seal and authorization attempts, the exact v16-v05 authorization stop, the v16-v07 finalizer stop, and no-contact fields.",
        "- The read-only WDDM pmon snapshot identified an active Type-C Python process and C+G desktop processes; lease v04 waits only on verified Type-C processes, retains C+G/G rows diagnostically, and fails closed on unidentifiable Type-C or unknown-type processes.",
        "",
        "## Bound frozen inputs",
        "",
        "Absolute paths are used only for inherited run-root receipts on D:. Workspace paths use canonical POSIX syntax.",
        "",
        "| Input Path | Bytes | SHA-256 | Role |",
        "| --- | ---: | --- | --- |",
    ]
    for rel, path, role in input_rows:
        size, sha = digest(path)
        content.append(f"| `{rel}` | {size} | `{sha}` | {role} |")
    content += [
        "",
        "## Bound source and build closure",
        "",
        "The closure includes inherited v06-v11 sources and receipts, failed v12-v16 map/contract/preseal/seal attempts, Track B v05/v04 runtime units, v16 issuer and versioned tooling, local imports, tests, contract tooling, and independent auditors. Bytecode, caches, and temporary output are excluded.",
        "",
        "| Path | Bytes | SHA-256 | Role |",
        "| --- | ---: | --- | --- |",
    ]
    for rel, path, role in source_rows:
        content.append(source_line(rel, path, role))
    content += [
        "",
        "## Source and preauthorization test receipts",
        "",
        "Predecessor receipts remain visible as history. Current Track E v16 auditor, authorization issuer v16, and contract tooling v16 receipts below must pass and bind the listed source versions.",
        "",
        "| Track | Path | Bytes | SHA-256 | Status |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for track, rel, path, status in receipt_rows:
        content.append(receipt_line(track, rel, path, status))
    content += [
        "",
        "## Boundary",
        "",
        "This source map only closes the v16 contract/source identity. It does not itself authorize the online parity, fresh-feature extraction, held-out-label opening, scoring, E4-A, or any later phase. Each E4-0 execution stage still requires its own separately scoped authorization.",
        "",
    ]
    encoded = "\n".join(content).encode("utf-8")
    safe_output_path(OUTPUT)
    with OUTPUT.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
    print(json.dumps({"status": "SOURCE_MAP_V16_V09_CREATED_UNAUTHORIZED", "path": str(OUTPUT),
                      "bytes": len(encoded), "sha256": hashlib.sha256(encoded).hexdigest(),
                      "source_rows": len(source_rows), "input_rows": len(input_rows),
                      "receipt_rows": len(receipt_rows)}, sort_keys=True))
    return 0


def safe_output_path(path: Path) -> None:
    root = WORKSPACE.resolve(strict=True)
    if path.exists() or path.is_symlink():
        raise RuntimeError(f"refusing existing source-map output path: {path}")
    try:
        relative = path.absolute().relative_to(WORKSPACE.absolute())
    except ValueError as exc:
        raise RuntimeError(f"source-map output path escapes workspace: {path}") from exc
    cursor = WORKSPACE
    for part in relative.parts[:-1]:
        cursor = cursor / part
        is_junction = getattr(cursor, "is_junction", None)
        if cursor.is_symlink() or (callable(is_junction) and is_junction()):
            raise RuntimeError(f"source-map output traverses symlink or junction: {cursor}")
    resolved_parent = path.parent.resolve(strict=True)
    try:
        resolved_parent.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"source-map output parent escapes workspace: {parent}") from exc
    cursor = root
    for part in resolved_parent.relative_to(root).parts:
        cursor = cursor / part
        is_junction = getattr(cursor, "is_junction", None)
        if cursor.is_symlink() or (callable(is_junction) and is_junction()):
            raise RuntimeError(f"source-map output traverses symlink or junction: {cursor}")


if __name__ == "__main__":
    raise SystemExit(main())
