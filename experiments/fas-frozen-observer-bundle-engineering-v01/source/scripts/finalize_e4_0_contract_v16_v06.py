#!/usr/bin/env python3
"""Finalize E4-0 v16 with unchanged v06 science and exact failed-v15 lineage."""
from __future__ import annotations
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_REL = "experiments/fas-frozen-observer-bundle-engineering-v01"
BASELINE_REL = f"{PROJECT_REL}/contracts/e4-0-contract-v06-final.json"
MAP_REL = f"{PROJECT_REL}/plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v16-v05.md"
OUTPUT_REL = f"{PROJECT_REL}/contracts/e4-0-contract-v16-v04-final.json"
BASELINE_SHA256 = "ea4f11cec5d65a3be7716c77febf5d448d8ebf1a5a4049aee5d25d51c0c50958"
IMMUTABLE = ("purpose", "authorization", "predecessors", "representation_abi", "population", "parity",
             "fresh_qualification", "truth_access", "resources", "phase_gates",
             "stop_rule", "E4_A_dependency", "execution_identity", "identity_collision_correction")
V06_SEAL_REL = f"{PROJECT_REL}/seals/e4-0-contract-v06-seal.json"
V06_SEAL_SHA256 = "799d1535a16ea6fbf2269206443addf96736ef8a70ca5ab3373cdd5e6a44605c"
V06_ROOT_SHA256 = "7344badf07476d19d9c6228f80d026a112c339e93daa75593e61031f68456e64"
V08_CONTRACT_SHA256 = "ec17befa2a65e0da589ee51792cde3c028e900aa919179b2c9c3365cc20c3e9b"
V08_CONTRACT_BYTES = 54286
V08_SEAL_SHA256 = "238d1fdb46ba3d8a9de1ae90e41a9b3c455ba65661bc98e8fe6fa5d21e3d3156"
V08_SEAL_BYTES = 68666
V08_ROOT_SHA256 = "e0093eacd70ce7cbf3b3a19045683ce5a7f4d4413748003e2d8e1446f131478d"
V08_AUDIT_SHA256 = "8e2fb068f0ce4acda3d91fe53f4f9b37fab9cffa49a2067ffdd939e95c862898"
V08_AUDIT_BYTES = 68220
V08_STOP_SHA256 = "99c937b1f8a2242609621b1210828b6ae1411e701cbe2074d655d90328904e4d"
V08_STOP_BYTES = 1997
V08_BINDINGS_SHA256 = "0c3e29a78d2d5eb14ffb573fdf1bc9baa91957488b2f95c7c0fe17412b550cdc"
V08_BINDINGS_BYTES = 4719
WDDM_SHA256 = "20ad334b87b3c6a36435f71382a906f6009e7427760d617d2d73a3baa380cc34"
WDDM_BYTES = 8151
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
V11_MAP_SHA256 = "d464e0e4898da33afcab6153f7f7df34be9f2a3f9ec499896ac703807f986b6e"
V11_MAP_BYTES = 82088
V11_CONTRACT_SHA256 = "9cefc7cf9ca8f367bceff3c1c9b7e84ab3e15f684326edf94354e33e3d1fb2fd"
V11_CONTRACT_BYTES = 72068
V11_PRESEAL_SHA256 = "a3ccc4181717af9a84b2e16fc57a7f8819d0fc646918f6f09f760e8bf2c0392d"
V11_PRESEAL_BYTES = 101751
V11_SEAL_SHA256 = "7f27371f3cb886208ff67ea7a19e2ca51577bfbc74e4f6611ca496ab9c13ebcd"
V11_SEAL_BYTES = 90814
V11_SEAL_ROOT_SHA256 = "dc7ec0731a6f637bd8aa6416bd74aba8e074e8bf0c936a1bda830e79c0afa6c3"
V11_POSTSEAL_SHA256 = "09822f935ef94c9307f3a9754dc8a408294de0f77832b7ef09f8e47d56272aa9"
V11_POSTSEAL_BYTES = 102930
V12_MAP_SHA256 = "61df89861d9540641305cdb0020a7bc95772a8adab529e5fdd62898e4c066930"
V12_MAP_BYTES = 91198
V12_CONTRACT_SHA256 = "9dee0e26b3eb1fcdbcc7146214745f8d699459bfdd23f15b8532e87cc9da3e75"
V12_CONTRACT_BYTES = 78271
V12_PRESEAL_SHA256 = "4ac87653ae964e3ede95876ba3a9a7a32402672331d1c25f9b41d06725131f24"
V12_PRESEAL_BYTES = 111784
V13_MAP_REL = f"{PROJECT_REL}/plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v13.md"
V13_MAP_BYTES = 86052
V13_MAP_SHA256 = "a06d436c5cee8305ab65a7cb77f34165f48ccdeee932b788a511a70663c47fc6"
V13_FINALIZER_REL = f"{PROJECT_REL}/source/scripts/finalize_e4_0_contract_v13.py"
V13_FINALIZER_BYTES = 52511
V13_FINALIZER_SHA256 = "03025d1e0e5ed52e7ef3920db0ef780139944fd209fa9d221ca071b42f16ed11"
V13_STOP_REL = f"{PROJECT_REL}/audits/e4-0-track-e/finalization-stop-v13-v01.json"
V13_STOP_BYTES = 1658
V13_STOP_SHA256 = "43e1270f5d395154ab713401558814503dc4fc143048d980447932750fa577dc"
V13_STOP_STATUS = "E4_0_V13_FINALIZATION_STOP_RECEIPT_STATUS_MISMATCH"
V13_STOP_DIAGNOSTIC = "receipt status mismatch or failure: experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/track-e-source-tests-v20.json"
V14_MAP_REL = f"{PROJECT_REL}/plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v14.md"
V14_MAP_BYTES = 89298
V14_MAP_SHA256 = "40f1d41123dd75093766c01f3e8073f584cf3a7c265d2fba0461ed72ced4fe8f"
V14_CONTRACT_REL = f"{PROJECT_REL}/contracts/e4-0-contract-v14-final.json"
V14_CONTRACT_BYTES = 86587
V14_CONTRACT_SHA256 = "9a195eaa7cbbdfff79ee9095c283c52bfb2e78baf40608eab86c0435c443b8f8"
V14_PRESEAL_REL = f"{PROJECT_REL}/audits/e4-0-track-e/track-e-preseal-receipt-v14.json"
V14_PRESEAL_BYTES = 112879
V14_PRESEAL_SHA256 = "d97d00209cc485d80af1d8a7faa0da15cbdf54a79357b13efe9b458ec4d97995"
V14_PRESEAL_STATUS = "E4_0_TRACK_E_PRESEAL_STOP_MISMATCHES_RECORDED_V14"
V15_MAP_REL = f"{PROJECT_REL}/plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v15.md"
V15_MAP_BYTES = 94630
V15_MAP_SHA256 = "3747444405a905ed8918d7939ce7e968915b02d6ebcee422d588f010d7fe50f1"
V15_CONTRACT_REL = f"{PROJECT_REL}/contracts/e4-0-contract-v15-final.json"
V15_CONTRACT_BYTES = 95055
V15_CONTRACT_SHA256 = "a29963988af2c7d1456e403a1cf219a915d29b2b7f4559b44ef175f60aa1d698"
V15_PRESEAL_REL = f"{PROJECT_REL}/audits/e4-0-track-e/track-e-preseal-receipt-v15.json"
V15_PRESEAL_BYTES = 118505
V15_PRESEAL_SHA256 = "66b9059a9b92c6711d704d1849bb60158003746b394c8d5bb1ebedb4b2a3113b"
V15_PRESEAL_STATUS = "E4_0_TRACK_E_PRESEAL_STOP_MISMATCHES_RECORDED_V15"
V16_FIRST_MAP_REL = f"{PROJECT_REL}/plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v16.md"
V16_FIRST_MAP_BYTES = 100236
V16_FIRST_MAP_SHA256 = "34543f8b437adcc5ae003e1638ff77e0503b0089d39c456bbadc6b1dcff03f07"
V16_FINALIZATION_STOP_REL = f"{PROJECT_REL}/audits/e4-0-track-e/finalization-stop-v16-v01.json"
V16_FINALIZATION_STOP_BYTES = 1767
V16_FINALIZATION_STOP_SHA256 = "ed84d2392b800a18ad66c38d89dff230d7f71f93900f98a23b92652ee8cee53f"
V16_FINALIZATION_STOP_STATUS = "E4_0_V16_FINALIZATION_STOP_RECEIPT_CLOSURE_MISMATCH"
V16_V02_MAP_REL = f"{PROJECT_REL}/plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v16-v02.md"
V16_V02_MAP_BYTES = 102759
V16_V02_MAP_SHA256 = "ae35747bd1108917c09b3ecba236d6a83f794367f0f0abb5b39834151628387d"
V16_V02_CONTRACT_REL = f"{PROJECT_REL}/contracts/e4-0-contract-v16-final.json"
V16_V02_CONTRACT_BYTES = 97804
V16_V02_CONTRACT_SHA256 = "65aea43be84c0016f6ecd95657020353d4f969c915d267d7add20779f2a3ad1c"
V16_V02_PRESEAL_REL = f"{PROJECT_REL}/audits/e4-0-track-e/track-e-preseal-receipt-v16-v02.json"
V16_V02_PRESEAL_BYTES = 128288
V16_V02_PRESEAL_SHA256 = "7d3636112ff63acb467e397f1a9a9cc8c1ffabbdddb026a8c6d5606090ae2c52"
V16_V02_PRESEAL_STATUS = "E4_0_TRACK_E_PRESEAL_STOP_MISMATCHES_RECORDED_V15"
V16_V02_PRESEAL_ISSUES = [
    "v16 amendment differs from the canonical flattened v12-v15 lineage or exact preserved no-contact stops",
    "contract implementation_sources does not exactly bind source-map rows by role",
    "source map includes an unregistered source-test receipt track: 'Initial Track E v15 pre-map'",
    "source map includes an unregistered source-test receipt track: 'Track E v15 pre-map'",
    "source map omits registered source-test receipt tracks: ['Predecessor Track E v15 pre-map attempt 1', 'Predecessor Track E v15 pre-map attempt 2']",
]
V16_V03_MAP_REL = f"{PROJECT_REL}/plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v16-v03.md"
V16_V03_MAP_BYTES = 106461
V16_V03_MAP_SHA256 = "b75ce6021d4f52ccf1791d8d473dcb56527dfba3edde16066b98135bb0f004a0"
V16_V03_CONTRACT_REL = f"{PROJECT_REL}/contracts/e4-0-contract-v16-v02-final.json"
V16_V03_CONTRACT_BYTES = 105950
V16_V03_CONTRACT_SHA256 = "b708b3e0411b4189371fbfd91f330839aa39ef8939e9a622565a47966a1a0c32"
V16_V03_PRESEAL_REL = f"{PROJECT_REL}/audits/e4-0-track-e/track-e-preseal-receipt-v16-v03.json"
V16_V03_PRESEAL_BYTES = 132329
V16_V03_PRESEAL_SHA256 = "c6eddaa8144d57263613f7ba466be4ce396a55de8e70aa2e8bf94ec767de2109"
V16_V03_PRESEAL_STATUS = "E4_0_TRACK_E_PRESEAL_STOP_MISMATCHES_RECORDED_V16_V03"
V16_V03_PRESEAL_ISSUES = ["v16 amendment differs from the canonical flattened v12-v15 lineage or exact preserved no-contact stops"]
V16_V04_MAP_REL = f"{PROJECT_REL}/plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v16-v04.md"
V16_V04_MAP_BYTES = 110067
V16_V04_MAP_SHA256 = "29c304ce6943d8d982e0ca7bae2d66be3bf2fb4b1d54ed5cec7a0090bf8ac414"
V16_V04_CONTRACT_REL = f"{PROJECT_REL}/contracts/e4-0-contract-v16-v03-final.json"
V16_V04_CONTRACT_BYTES = 110905
V16_V04_CONTRACT_SHA256 = "44dc5b8fd06874c5478cc7b026d30d543a8c8a0f38697c59ea4ce0ce583d9a06"
V16_V04_PRESEAL_REL = f"{PROJECT_REL}/audits/e4-0-track-e/track-e-preseal-receipt-v16-v04.json"
V16_V04_PRESEAL_BYTES = 136715
V16_V04_PRESEAL_SHA256 = "721478570cd3d9a15645424045046ea788ad572430305cd16e19956eddee6c09"
V16_V04_SEALER_REL = f"{PROJECT_REL}/source/scripts/seal_e4_0_contract_v16_v04.py"
V16_V04_SEALER_BYTES = 17761
V16_V04_SEALER_SHA256 = "87cd4e9aa33ca450d5be4dfe771ae0c21a8acb52344b35efafa206e444eee013"
V16_V04_SEAL_STOP_REL = f"{PROJECT_REL}/audits/e4-0-track-e/contract-seal-stop-v16-v04-v01.json"
V16_V04_SEAL_STOP_BYTES = 2042
V16_V04_SEAL_STOP_SHA256 = "e7fc5c6018470ffc45388ef9f00fe417cdd074e03eb8fcaa60ef691db9c87df2"
V16_V04_SEAL_STOP_STATUS = "E4_0_CONTRACT_SEAL_STOP_DUPLICATE_MEMBER_PATH_V16_V04"
V16_V04_SEAL_STOP_DIAGNOSTIC = "duplicate seal member resolved path: experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/finalize_e4_0_contract_v13.py"
V15_PRESEAL_ISSUES = [
    "v15 amendment does not exactly preserve v14 lineage and bind its failed-preseal attempt",
    "contract implementation_sources does not exactly bind source-map rows by role",
    "source-test receipt track/path/status differs from its registered identity: 'Predecessor Track E v07 pre-map': expected ('experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/track-e-source-tests-v15.json', 'TRACK_E_SOURCE_TESTS_PASS_V07_PREMAP_SYNTHETIC_AUDITOR'), got ('experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/track-e-source-tests-v14.json', 'TRACK_E_SOURCE_TESTS_PASS_V07_PREMAP_SYNTHETIC_AUDITOR')",
]
V16_SCOPE = "The v16-v05 update preserves the v06 scientific object and v11 last sealed predecessor, carries forward canonical v12-v15 lineage and all no-contact v16 attempts, binds the exact failed v16-v04 contract seal attempt, and seals a shared source/input path only once after verifying its bound bytes and hash. No scientific field or execution boundary changes; no E4 stage authorization is granted."
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
V14_FAILED_PRESEAL_ATTEMPT = {
    "source_map": {"path": V14_MAP_REL, "bytes": V14_MAP_BYTES, "sha256": V14_MAP_SHA256},
    "contract": {"path": V14_CONTRACT_REL, "bytes": V14_CONTRACT_BYTES, "sha256": V14_CONTRACT_SHA256},
    "preseal_receipt": {"path": V14_PRESEAL_REL, "bytes": V14_PRESEAL_BYTES,
                        "sha256": V14_PRESEAL_SHA256, "status": V14_PRESEAL_STATUS},
    "issues": list(V14_PRESEAL_ISSUES), "pass": False, "final_seal": None,
    "population_truth_files_opened": False, "template_or_joint_truth_opened": False,
}
V15_SCOPE = "The v15 update preserves the v06 scientific object and complete v14/v13/v12 lineage. It corrects only the independent Track E v14 auditor's receipt registry to the exact preserved issuer-v13/tooling-v13 and tooling-v14 receipt identities, corrects the v12 preseal nested contract identity schema, and adds the v13 finalizer source as a frozen input in a new v15 source map. The failed v14 preseal is bound exactly; no scientific field or execution boundary changes; no E4 stage authorization is granted."
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
    "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V05",
    "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V06",
    "TRACK_E_SOURCE_TESTS_PASS_V16_PREMAP_SYNTHETIC_AUDITOR_V05",
    "TRACK_E_SOURCE_TESTS_PASS_V16_PREMAP_SYNTHETIC_AUDITOR_V06",
    "PASS_SYNTHETIC_TESTS_V16_V03",
    "PASS_SYNTHETIC_TESTS_V16_V04",
    "PASS_SYNTHETIC_TESTS_V16_V02",
    "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V02",
    "PASS_SYNTHETIC_TESTS_V02",
    "PASS_SYNTHETIC_TESTS_V16",
    "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V16",
}
CURRENT_TRACK_STATUS = {
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
    "Authorization issuer v16": "PASS_SYNTHETIC_TESTS",
    "Authorization issuer v16 v02": "PASS_SYNTHETIC_TESTS_V16_V02",
    "Initial Contract tooling v16": "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS",
    "Predecessor Contract tooling v16 v02": "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V02",
    "Contract tooling v16": "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V03",
    "Contract tooling v16 v04 v02": "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V04",
    "Track E v16 pre-map v05": "TRACK_E_SOURCE_TESTS_PASS_V16_PREMAP_SYNTHETIC_AUDITOR_V05",
    "Authorization issuer v16 v03": "PASS_SYNTHETIC_TESTS_V16_V03",
    "Contract tooling v16 v05": "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V05",
    "Track E v16 pre-map v06": "TRACK_E_SOURCE_TESTS_PASS_V16_PREMAP_SYNTHETIC_AUDITOR_V06",
    "Authorization issuer v16 v04": "PASS_SYNTHETIC_TESTS_V16_V04",
    "Contract tooling v16 v06": "PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS_V06",
}


def scientific_projection(contract: dict[str, Any]) -> dict[str, Any]:
    projection = {key: contract.get(key) for key in IMMUTABLE}
    design = contract.get("design_inputs", {})
    projection["design_inputs"] = {
        key: value for key, value in design.items()
        if not key.startswith("implementation_source_map_")
    }
    return projection


def require_scientific_invariance(candidate: dict[str, Any], baseline: dict[str, Any]) -> None:
    if scientific_projection(candidate) != scientific_projection(baseline):
        raise RuntimeError("frozen scientific fields differ from the sealed v06 baseline")


def sha256_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1 << 20):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def parse_tables(path: Path) -> list[tuple[list[str], list[list[str]]]]:
    result = []
    header = None
    rows: list[list[str]] = []

    def close() -> None:
        nonlocal header, rows
        if header is not None and rows:
            result.append((header, rows))
        header, rows = None, []

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not (line.startswith("|") and line.endswith("|")):
            close()
            continue
        cells = [part.strip().strip(chr(96) + " ") for part in line.strip("|").split("|")]
        if cells and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells):
            continue
        if header is None:
            header = cells
        elif len(cells) == len(header):
            rows.append(cells)
    close()
    return result


def workspace_file(workspace: Path, rel: str) -> Path:
    if not rel or rel.startswith("/") or "\\" in rel or "\t" in rel or "\n" in rel or ".." in Path(rel).parts:
        raise RuntimeError(f"unsafe workspace-relative path: {rel!r}")
    path = (workspace / Path(rel)).resolve(strict=True)
    path.relative_to(workspace.resolve())
    return path


def source_rows(map_path: Path, workspace: Path) -> list[dict[str, Any]]:
    matches = [rows for head, rows in parse_tables(map_path)
               if [h.lower().replace("-", "") for h in head] == ["path", "bytes", "sha256", "role"]]
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one source closure table, found {len(matches)}")
    result = []
    seen: set[str] = set()
    for rel, size_text, digest, role in matches[0]:
        path = workspace_file(workspace, rel)
        identity = unicodedata.normalize("NFC", str(path)).casefold()
        if identity in seen or not size_text.isdecimal() or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise RuntimeError(f"malformed or repeated source row: {rel}")
        size, actual = sha256_file(path)
        if size != int(size_text) or actual != digest:
            raise RuntimeError(f"source identity mismatch: {rel}")
        seen.add(identity)
        result.append({"path": rel, "bytes": size, "sha256": actual, "role": role})
    if not result:
        raise RuntimeError("source closure is empty")
    return result


def receipt_rows(map_path: Path, workspace: Path) -> list[dict[str, Any]]:
    matches = [rows for head, rows in parse_tables(map_path)
               if [h.lower().replace("-", "") for h in head] == ["track", "path", "bytes", "sha256", "status"]]
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one source receipt table, found {len(matches)}")
    result = []
    seen_paths: set[str] = set()
    seen_tracks: set[str] = set()
    for track, rel, size_text, digest, status in matches[0]:
        if not size_text.isdecimal() or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise RuntimeError(f"malformed receipt row: {rel}")
        path = workspace_file(workspace, rel)
        path_key = unicodedata.normalize("NFC", str(path.resolve(strict=True))).casefold()
        if path_key in seen_paths or track in seen_tracks:
            raise RuntimeError(f"duplicate source receipt path or track: {track}: {rel}")
        size, actual = sha256_file(path)
        if size != int(size_text) or actual != digest:
            raise RuntimeError(f"receipt identity mismatch: {rel}")
        if track == "Initial Authorization issuer v15" and (
                rel != f"{PROJECT_REL}/audits/e4-0-auth-issuer-v15/source-tests-v01.json"
                or (size, actual) != (V15_ISSUER_V01_BYTES, V15_ISSUER_V01_SHA256)):
            raise RuntimeError("preserved initial v15 issuer receipt identity changed")
        if track == "Initial Track E v15 pre-map" and (
                rel != f"{PROJECT_REL}/audits/e4-0-track-e/track-e-source-tests-v25.json"
                or (size, actual) != (V15_TRACK_E_V01_BYTES, V15_TRACK_E_V01_SHA256)):
            raise RuntimeError("preserved initial v15 Track E receipt identity changed")
        if track == "Initial Contract tooling v15" and (
                rel != f"{PROJECT_REL}/audits/e4-0-track-e/contract-tooling-source-tests-v15.json"
                or (size, actual) != (V15_TOOLING_V01_BYTES, V15_TOOLING_V01_SHA256)):
            raise RuntimeError("preserved initial v15 tooling receipt identity changed")
        if track == "Predecessor Contract tooling v15 v02" and (
                rel != f"{PROJECT_REL}/audits/e4-0-track-e/contract-tooling-source-tests-v15-v02.json"
                or (size, actual) != (V15_TOOLING_V02_BYTES, V15_TOOLING_V02_SHA256)):
            raise RuntimeError("preserved v02 v15 tooling receipt identity changed")
        payload = json.loads(path.read_text(encoding="utf-8"))
        actual_status = str(payload.get("status", ""))
        expected_current = CURRENT_TRACK_STATUS.get(track)
        status_allowed = status == expected_current if expected_current is not None else status in PASS_STATUSES
        if actual_status != status or not status_allowed:
            raise RuntimeError(f"receipt status mismatch or failure: {rel}")
        result.append({"track": track, "path": rel, "bytes": size, "sha256": actual, "status": status})
        seen_paths.add(path_key)
        seen_tracks.add(track)
    if not result:
        raise RuntimeError("source map binds no source validation receipts")
    return result


def grouped(rows: list[dict[str, Any]], predicate: Any, label: str) -> dict[str, Any]:
    selected = [row for row in rows if predicate(row["path"])]
    if not selected:
        raise RuntimeError(f"source closure is missing {label}")
    return {"files": selected}


def implementation_source_projection(
    sources: list[dict[str, Any]], source_map: dict[str, Any]
) -> dict[str, Any]:
    """Build the contract role projection from the frozen source rows."""
    return {
        "source_map": source_map,
        "e4_population_generator": grouped(
            sources, lambda p: any(x in p for x in (
                "/source/e4-population-v02/", "/source/panel-generator-v04/", "/source/e4-support-plan-v11/"
            )), "population generator"),
        "e4_online_feature_and_parity_runner": grouped(
            sources, lambda p: any(p.endswith("/" + name) for name in (
                "e4_online_parity_v05.py", "e4_runner_common_v05.py", "e4_runner_artifacts_v05.py",
                "e4_runner_modes_v05.py", "e4_gpu_lease_v04.py", "test_e4_runner_v05.py"
            )), "online/parity runner"),
        "e4_fresh_scorer": grouped(
            sources, lambda p: "/source/scripts/e4_fresh_scorer_v04/" in p, "fresh scorer"),
        "e4_stage_authorization_issuer": grouped(
            sources, lambda p: any(p.endswith("/" + name) for name in (
                "issue_e4_stage_authorization_v16.py", "test_e4_stage_authorization_v16.py",
                "issue_e4_stage_authorization_v16_v02.py", "test_e4_stage_authorization_v16_v02.py",
                "issue_e4_stage_authorization_v16_v03.py", "test_e4_stage_authorization_v16_v03.py",
                "issue_e4_stage_authorization_v16_v04.py", "test_e4_stage_authorization_v16_v04.py"
            )), "stage authorization issuer"),
        "e4_independent_auditor": grouped(
            sources, lambda p: "/source/scripts/e4_independent_audit_v04/" in p
            or any(p.endswith("/audits/e4-0-track-e/" + name) for name in (
                "audit_e4_0_track_e_v15.py", "test_audit_e4_0_track_e_v15.py",
                "audit_e4_0_track_e_v15_v02.py", "test_audit_e4_0_track_e_v15_v02.py",
                "audit_e4_0_track_e_v16.py", "test_audit_e4_0_track_e_v16.py",
                "audit_e4_0_track_e_v16_v02.py", "test_audit_e4_0_track_e_v16_v02.py",
                "audit_e4_0_track_e_v16_v03.py", "test_audit_e4_0_track_e_v16_v03.py",
                "audit_e4_0_track_e_v16_v04.py", "test_audit_e4_0_track_e_v16_v04.py",
                "audit_e4_0_track_e_v16_v05.py", "test_audit_e4_0_track_e_v16_v05.py",
                "audit_e4_0_track_e_v16_v06.py", "test_audit_e4_0_track_e_v16_v06.py",
            )), "independent auditor"),
        "e4_contract_seal_and_source_map_tooling": grouped(
            sources, lambda p: any(p.endswith("/" + name) for name in (
                "build_e4_0_source_map_v16_v02.py", "finalize_e4_0_contract_v16_v02.py",
                "test_e4_0_contract_v16_v02.py", "build_e4_0_source_map_v16_v03.py",
                "finalize_e4_0_contract_v16_v03.py", "seal_e4_0_contract_v16_v02.py",
                "test_e4_0_contract_v16_v03.py", "build_e4_0_source_map_v16_v04.py",
                "finalize_e4_0_contract_v16_v04.py", "seal_e4_0_contract_v16_v03.py",
                "test_e4_0_contract_v16_v04.py",
                "build_e4_0_source_map_v16_v05.py", "finalize_e4_0_contract_v16_v05.py",
                "seal_e4_0_contract_v16_v04.py", "test_e4_0_contract_v16_v05.py",
                "build_e4_0_source_map_v16_v06.py", "finalize_e4_0_contract_v16_v06.py",
                "seal_e4_0_contract_v16_v05.py", "test_e4_0_contract_v16_v06.py",
            )), "v16 contract/source-map/seal tooling"),
    }


def canonical_receipt_source_path(value: str) -> str:
    if value.startswith("experiments/"):
        return value
    return f"{PROJECT_REL}/{value}"


def receipt_bindings(payload: dict[str, Any], track: str) -> list[dict[str, Any]]:
    if track.startswith("Track B"):
        value = payload.get("bound_sources")
    elif track.startswith("Track C") or track.startswith("Track D") or track.startswith("Authorization issuer"):
        value = payload.get("source_files")
    elif track.startswith("Track E v08") or track.startswith("Track E v09") or track.startswith("Track E v10") or track.startswith("Track E v11") or track.startswith("Track E v12"):
        value = payload.get("sources")
    elif track.startswith("Track E v15"):
        value = payload.get("sources")
    elif track.startswith("Track E v16"):
        value = payload.get("sources")
    elif track.startswith("Contract tooling v16"):
        value = payload.get("source_bindings")
    elif track.startswith("Contract tooling"):
        value = payload.get("source_bindings")
    else:
        return []
    if isinstance(value, dict):
        value = [{"path": key, **item} for key, item in value.items()]
    if not isinstance(value, list) or not value:
        raise RuntimeError(f"receipt has no source identity bindings: {track}")
    return value


def verify_receipt_source_closure(receipts: list[dict[str, Any]], sources: list[dict[str, Any]], workspace: Path) -> None:
    source_by_path = {row["path"]: row for row in sources}
    for receipt in receipts:
        if receipt["track"] in (
                "Initial Track E v15 pre-map", "Initial Authorization issuer v15",
                "Initial Contract tooling v15", "Predecessor Contract tooling v15 v02",
                "Initial Track E v16 pre-map", "Initial Contract tooling v16"):
            continue
        path = workspace_file(workspace, receipt["path"])
        payload = json.loads(path.read_text(encoding="utf-8"))
        bound: set[str] = set()
        for binding in receipt_bindings(payload, receipt["track"]):
            rel = canonical_receipt_source_path(str(binding.get("path", "")))
            source = source_by_path.get(rel)
            if source is None:
                raise RuntimeError(f"receipt source is not in source closure: {receipt['track']}: {rel}")
            if rel in bound:
                raise RuntimeError(f"receipt repeats a tested source: {receipt['track']}: {rel}")
            if binding.get("bytes") != source["bytes"] or binding.get("sha256") != source["sha256"]:
                raise RuntimeError(f"receipt tested source differs from source closure: {receipt['track']}: {rel}")
            bound.add(rel)
        track = receipt["track"]
        if track.startswith("Track B"):
            names = {"e4_runner_common_v05.py", "e4_runner_artifacts_v05.py", "e4_gpu_lease_v04.py",
                     "e4_runner_modes_v05.py", "e4_online_parity_v05.py", "test_e4_runner_v05.py"}
            expected = {rel for rel in source_by_path if any(rel.endswith("/" + name) for name in names)}
        elif track.startswith("Track C"):
            expected = {rel for rel in source_by_path if "/source/scripts/e4_fresh_scorer_v04/" in rel}
        elif track.startswith("Track D"):
            expected = {rel for rel in source_by_path if "/source/scripts/e4_independent_audit_v04/" in rel}
        elif track.startswith("Track E v08"):
            expected = {rel for rel in source_by_path if rel.endswith((
                "/audits/e4-0-track-e/audit_e4_0_track_e_v08.py",
                "/audits/e4-0-track-e/test_audit_e4_0_track_e_v08.py",
            ))}
        elif track.startswith("Track E v09"):
            expected = {rel for rel in source_by_path if rel.endswith((
                "/audits/e4-0-track-e/audit_e4_0_track_e_v09.py",
                "/audits/e4-0-track-e/test_audit_e4_0_track_e_v09.py",
            ))}
        elif track.startswith("Track E v10"):
            expected = {rel for rel in source_by_path if rel.endswith((
                "/audits/e4-0-track-e/audit_e4_0_track_e_v10.py",
                "/audits/e4-0-track-e/test_audit_e4_0_track_e_v10.py",
            ))}
        elif track.startswith("Track E v11"):
            expected = {rel for rel in source_by_path if rel.endswith((
                "/audits/e4-0-track-e/audit_e4_0_track_e_v11.py",
                "/audits/e4-0-track-e/test_audit_e4_0_track_e_v11.py",
            ))}
        elif track.startswith("Track E v12"):
            expected = {rel for rel in source_by_path if rel.endswith((
                "/audits/e4-0-track-e/audit_e4_0_track_e_v15.py",
                "/audits/e4-0-track-e/test_audit_e4_0_track_e_v15.py",
            ))}
        elif track.startswith("Track E v15"):
            expected = {rel for rel in source_by_path if rel.endswith((
                "/audits/e4-0-track-e/audit_e4_0_track_e_v15_v02.py",
                "/audits/e4-0-track-e/test_audit_e4_0_track_e_v15_v02.py",
            ))}
        elif track.startswith("Track E v16"):
            if track.startswith("Track E v16 pre-map v06"):
                expected = {rel for rel in source_by_path if rel.endswith((
                    "/audits/e4-0-track-e/audit_e4_0_track_e_v16_v06.py",
                    "/audits/e4-0-track-e/test_audit_e4_0_track_e_v16_v06.py",
                ))}
            elif track.startswith("Track E v16 pre-map v05"):
                expected = {rel for rel in source_by_path if rel.endswith((
                    "/audits/e4-0-track-e/audit_e4_0_track_e_v16_v05.py",
                    "/audits/e4-0-track-e/test_audit_e4_0_track_e_v16_v05.py",
                ))}
            elif track.startswith("Track E v16 pre-map v04"):
                expected = {rel for rel in source_by_path if rel.endswith((
                    "/audits/e4-0-track-e/audit_e4_0_track_e_v16_v04.py",
                    "/audits/e4-0-track-e/test_audit_e4_0_track_e_v16_v04.py",
                ))}
            else:
                expected = {rel for rel in source_by_path if rel.endswith((
                    "/audits/e4-0-track-e/audit_e4_0_track_e_v16_v03.py",
                    "/audits/e4-0-track-e/test_audit_e4_0_track_e_v16_v03.py",
                ))}
        elif track.startswith("Authorization issuer v15"):
            expected = {rel for rel in source_by_path if rel.endswith((
                "/source/scripts/issue_e4_stage_authorization_v15.py",
                "/source/tests/test_e4_stage_authorization_v15.py",
            ))}
        elif track.startswith("Authorization issuer v16"):
            suffixes = (
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
            expected = {rel for rel in source_by_path if rel.endswith(suffixes)}
        elif track.startswith("Contract tooling v15"):
            names = {"build_e4_0_source_map_v15.py", "finalize_e4_0_contract_v15.py",
                     "seal_e4_0_contract_v15.py", "test_e4_0_contract_v15.py"}
            expected = {rel for rel in source_by_path if any(rel.endswith("/" + name) for name in names)}
        elif track.startswith("Contract tooling v16"):
            if track.startswith("Contract tooling v16 v06"):
                names = {"build_e4_0_source_map_v16_v06.py", "finalize_e4_0_contract_v16_v06.py",
                         "seal_e4_0_contract_v16_v05.py", "test_e4_0_contract_v16_v06.py"}
            elif track.startswith("Contract tooling v16 v05"):
                names = {"build_e4_0_source_map_v16_v05.py", "finalize_e4_0_contract_v16_v05.py",
                         "seal_e4_0_contract_v16_v04.py", "test_e4_0_contract_v16_v05.py"}
            elif track.startswith("Contract tooling v16 v04"):
                names = {"build_e4_0_source_map_v16_v04.py", "finalize_e4_0_contract_v16_v04.py",
                         "seal_e4_0_contract_v16_v03.py", "test_e4_0_contract_v16_v04.py"}
            else:
                names = {"build_e4_0_source_map_v16_v03.py", "finalize_e4_0_contract_v16_v03.py",
                         "seal_e4_0_contract_v16_v02.py", "test_e4_0_contract_v16_v03.py"}
            expected = {rel for rel in source_by_path if any(rel.endswith("/" + name) for name in names)}
        else:
            continue
        if bound != expected:
            missing, extra = sorted(expected - bound), sorted(bound - expected)
            raise RuntimeError(f"receipt source closure is not exact for {track}: missing={missing}, extra={extra}")


def safe_output_path(path: Path, workspace: Path) -> None:
    root = workspace.resolve(strict=True)
    if path.exists() or path.is_symlink():
        raise RuntimeError(f"refusing existing final contract path: {path}")
    try:
        relative = path.absolute().relative_to(workspace.absolute())
    except ValueError as exc:
        raise RuntimeError(f"final contract output escapes workspace: {path}") from exc
    cursor = workspace
    for part in relative.parts[:-1]:
        cursor = cursor / part
        is_junction = getattr(cursor, "is_junction", None)
        if cursor.is_symlink() or (callable(is_junction) and is_junction()):
            raise RuntimeError(f"final contract output traverses symlink or junction: {cursor}")
    parent = path.parent.resolve(strict=True)
    try:
        parent.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"final contract parent escapes workspace: {path.parent}") from exc
    cursor = root
    for part in path.parent.resolve().relative_to(root).parts:
        cursor = cursor / part
        is_junction = getattr(cursor, "is_junction", None)
        if cursor.is_symlink() or (callable(is_junction) and is_junction()):
            raise RuntimeError(f"final contract output traverses symlink or junction: {cursor}")


def build_final_contract(workspace: Path) -> dict[str, Any]:
    baseline_path = workspace / BASELINE_REL
    baseline_bytes, baseline_sha = sha256_file(baseline_path)
    if baseline_sha != BASELINE_SHA256:
        raise RuntimeError("immutable sealed v06 baseline hash mismatch")
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    if baseline.get("contract_id") != "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V06" or baseline.get("status") != "SEALED":
        raise RuntimeError("v06 baseline contract identity/status mismatch")
    prior_seal_path = workspace / V06_SEAL_REL
    prior_seal_bytes, prior_seal_sha = sha256_file(prior_seal_path)
    if prior_seal_bytes != 35340 or prior_seal_sha != V06_SEAL_SHA256:
        raise RuntimeError("sealed v06 predecessor manifest identity changed")
    prior_seal = json.loads(prior_seal_path.read_text(encoding="utf-8"))
    if prior_seal.get("seal_id") != "FAS_E4_0_CONTRACT_V06_SEAL" or prior_seal.get("root_sha256") != V06_ROOT_SHA256:
        raise RuntimeError("sealed v06 predecessor root/identity mismatch")
    map_path = workspace / MAP_REL
    map_bytes, map_sha = sha256_file(map_path)
    sources = source_rows(map_path, workspace)
    receipts = receipt_rows(map_path, workspace)
    verify_receipt_source_closure(receipts, sources, workspace)
    first_v16_map_path = workspace / V16_FIRST_MAP_REL
    first_v16_stop_path = workspace / V16_FINALIZATION_STOP_REL
    first_v16_map_identity = sha256_file(first_v16_map_path)
    first_v16_stop_identity = sha256_file(first_v16_stop_path)
    if first_v16_map_identity != (V16_FIRST_MAP_BYTES, V16_FIRST_MAP_SHA256):
        raise RuntimeError("preserved first v16 source-map candidate identity changed")
    if first_v16_stop_identity != (V16_FINALIZATION_STOP_BYTES, V16_FINALIZATION_STOP_SHA256):
        raise RuntimeError("preserved v16 finalizer stop receipt identity changed")
    first_v16_stop = json.loads(first_v16_stop_path.read_text(encoding="utf-8"))
    if (first_v16_stop.get("status") != V16_FINALIZATION_STOP_STATUS
            or first_v16_stop.get("contract_candidate_written") is not False
            or first_v16_stop.get("seal_written") is not False
            or first_v16_stop.get("authorization_written") is not False
            or first_v16_stop.get("tokenizer_contact") is not False
            or first_v16_stop.get("model_contact") is not False
            or first_v16_stop.get("cuda_initialized") is not False
            or first_v16_stop.get("labels_opened") is not False):
        raise RuntimeError("first v16 finalizer stop is not the exact no-contact source-closure stop")
    v10_paths = {
        "contract": (f"{PROJECT_REL}/contracts/e4-0-contract-v10-final.json", V10_CONTRACT_BYTES, V10_CONTRACT_SHA256),
        "map": (f"{PROJECT_REL}/plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v09.md", V10_MAP_BYTES, V10_MAP_SHA256),
        "preseal": (f"{PROJECT_REL}/audits/e4-0-track-e/track-e-preseal-receipt-v10.json", V10_PRESEAL_BYTES, V10_PRESEAL_SHA256),
        "seal": (f"{PROJECT_REL}/seals/e4-0-contract-v10-seal.json", V10_SEAL_BYTES, V10_SEAL_SHA256),
        "postseal_v01": (f"{PROJECT_REL}/audits/e4-0-track-e/track-e-postseal-receipt-v10.json", V10_POSTSEAL_V01_BYTES, V10_POSTSEAL_V01_SHA256),
        "postseal_v02": (f"{PROJECT_REL}/audits/e4-0-track-e/track-e-postseal-receipt-v10-v02.json", V10_POSTSEAL_V02_BYTES, V10_POSTSEAL_V02_SHA256),
    }
    v10_identity: dict[str, dict[str, Any]] = {}
    for name, (rel, expected_bytes, expected_sha) in v10_paths.items():
        actual_bytes, actual_sha = sha256_file(workspace / rel)
        if (actual_bytes, actual_sha) != (expected_bytes, expected_sha):
            raise RuntimeError(f"preserved v10 predecessor artifact changed: {name}")
        v10_identity[name] = {"path": rel, "bytes": actual_bytes, "sha256": actual_sha}
    v10_contract = json.loads((workspace / v10_identity["contract"]["path"]).read_text(encoding="utf-8"))
    v10_seal = json.loads((workspace / v10_identity["seal"]["path"]).read_text(encoding="utf-8"))
    v10_preseal = json.loads((workspace / v10_identity["preseal"]["path"]).read_text(encoding="utf-8"))
    v10_stop1 = json.loads((workspace / v10_identity["postseal_v01"]["path"]).read_text(encoding="utf-8"))
    v10_stop2 = json.loads((workspace / v10_identity["postseal_v02"]["path"]).read_text(encoding="utf-8"))
    expected_v10_issues = [
        "v10 seal omits required member paths: ['experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v07-final.json', 'experiments/fas-frozen-observer-bundle-engineering-v01/seals/e4-0-contract-v07-seal.json']",
        "v10 seal lacks exact scientific-baseline/immediate-predecessor member: E4_0_CONTRACT_V07_SUPERSEDED",
        "v10 seal lacks exact scientific-baseline/immediate-predecessor member: E4_0_CONTRACT_V07_SEAL_SUPERSEDED",
    ]
    if (v10_contract.get("contract_id") != "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V10"
            or v10_contract.get("status") != "SEALED"
            or v10_seal.get("seal_id") != "FAS_E4_0_CONTRACT_V10_SEAL"
            or v10_seal.get("status") != "SEALED"
            or v10_seal.get("root_sha256") != V10_SEAL_ROOT_SHA256
            or v10_preseal.get("status") != "E4_0_TRACK_E_PRESEAL_PASS_V10_CONTRACT_AND_SOURCE_MAP_CLOSED"
            or v10_preseal.get("pass") is not True or v10_preseal.get("final_seal") is not None
            or v10_stop1.get("status") != "E4_0_TRACK_E_POSTSEAL_STOP_MISMATCHES_RECORDED_V10"
            or v10_stop1.get("issues") != ["postseal mode requires a contract seal"]
            or v10_stop2.get("status") != "E4_0_TRACK_E_POSTSEAL_STOP_MISMATCHES_RECORDED_V10"
            or v10_stop2.get("issues") != expected_v10_issues
            or v10_stop2.get("final_seal", {}).get("root_match") is not True
            or v10_stop2.get("final_seal", {}).get("member_set_exact") is not False):
        raise RuntimeError("v10 failed postseal member-inventory history differs from bound receipts")
    v11_paths = {
        "contract": (f"{PROJECT_REL}/contracts/e4-0-contract-v11-final.json", V11_CONTRACT_BYTES, V11_CONTRACT_SHA256),
        "map": (f"{PROJECT_REL}/plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v10.md", V11_MAP_BYTES, V11_MAP_SHA256),
        "preseal": (f"{PROJECT_REL}/audits/e4-0-track-e/track-e-preseal-receipt-v11.json", V11_PRESEAL_BYTES, V11_PRESEAL_SHA256),
        "seal": (f"{PROJECT_REL}/seals/e4-0-contract-v11-seal.json", V11_SEAL_BYTES, V11_SEAL_SHA256),
        "postseal": (f"{PROJECT_REL}/audits/e4-0-track-e/track-e-postseal-receipt-v11.json", V11_POSTSEAL_BYTES, V11_POSTSEAL_SHA256),
    }
    v11_identity: dict[str, dict[str, Any]] = {}
    for name, (rel, expected_bytes, expected_sha) in v11_paths.items():
        actual_bytes, actual_sha = sha256_file(workspace / rel)
        if (actual_bytes, actual_sha) != (expected_bytes, expected_sha):
            raise RuntimeError(f"preserved v11 predecessor artifact changed: {name}")
        v11_identity[name] = {"path": rel, "bytes": actual_bytes, "sha256": actual_sha}
    v11_contract = json.loads((workspace / v11_identity["contract"]["path"]).read_text(encoding="utf-8"))
    v11_seal = json.loads((workspace / v11_identity["seal"]["path"]).read_text(encoding="utf-8"))
    v11_preseal = json.loads((workspace / v11_identity["preseal"]["path"]).read_text(encoding="utf-8"))
    v11_stop = json.loads((workspace / v11_identity["postseal"]["path"]).read_text(encoding="utf-8"))
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
            or v11_stop.get("pass") is not False or v11_stop.get("issues") != expected_v11_issues
            or v11_stop.get("final_seal", {}).get("root_match") is not True
            or v11_stop.get("final_seal", {}).get("member_set_exact") is not False
            or v11_stop.get("final_seal", {}).get("entry_count") != 238
            or v11_stop.get("final_seal", {}).get("expected_member_count") != 240
            or any(v11_stop.get(key) is not False for key in (
                "population_truth_files_opened", "template_or_joint_truth_opened"))):
        raise RuntimeError("v11 failed postseal stop does not match exact missing-v08-member evidence")

    v12_paths = {
        "map": (f"{PROJECT_REL}/plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v11.md", V12_MAP_BYTES, V12_MAP_SHA256),
        "contract": (f"{PROJECT_REL}/contracts/e4-0-contract-v12-final.json", V12_CONTRACT_BYTES, V12_CONTRACT_SHA256),
        "preseal": (f"{PROJECT_REL}/audits/e4-0-track-e/track-e-preseal-receipt-v12.json", V12_PRESEAL_BYTES, V12_PRESEAL_SHA256),
    }
    v12_identity: dict[str, dict[str, Any]] = {}
    failed_v12_map_path = f"{PROJECT_REL}/plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v12.md"
    failed_v12_map_binding = {"path": failed_v12_map_path, "bytes": 100147,
                              "sha256": "697a438d99ae8897a3dcb390783ef8ab65c17bd1ffcca16465ffb7f3a4d74073"}
    actual_failed_map_bytes, actual_failed_map_sha = sha256_file(workspace / failed_v12_map_path)
    if (actual_failed_map_bytes, actual_failed_map_sha) != (failed_v12_map_binding["bytes"], failed_v12_map_binding["sha256"]):
        raise RuntimeError("preserved failed v12 generated source-map identity changed")
    for name, (rel, expected_bytes, expected_sha) in v12_paths.items():
        actual_bytes, actual_sha = sha256_file(workspace / rel)
        if (actual_bytes, actual_sha) != (expected_bytes, expected_sha):
            raise RuntimeError(f"preserved failed v12 preseal artifact changed: {name}")
        v12_identity[name] = {"path": rel, "bytes": actual_bytes, "sha256": actual_sha}
    v12_contract = json.loads((workspace / v12_identity["contract"]["path"]).read_text(encoding="utf-8"))
    v12_preseal = json.loads((workspace / v12_identity["preseal"]["path"]).read_text(encoding="utf-8"))
    if (v12_contract.get("contract_id") != "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V12"
            or v12_contract.get("status") != "SEALED"
            or v12_preseal.get("status") != "E4_0_TRACK_E_PRESEAL_STOP_MISMATCHES_RECORDED_V12"
            or v12_preseal.get("issues") != ["v12 amendment does not preserve v11 lineage or bind the exact v08 inventory repair"]
            or v12_preseal.get("pass") is not False or v12_preseal.get("final_seal") is not None
            or any(v12_preseal.get(key) is not False for key in (
                "population_truth_files_opened", "template_or_joint_truth_opened"))
            or any(v12_preseal.get(key) is not None for key in (
                "authorization_written", "tokenizer_contact", "model_contact", "cuda_initialized",
                "gpu_lease_acquired", "feature_cache_created", "labels_opened"))):
        raise RuntimeError("preserved failed v12 candidate/stop differs from exact no-contact lineage")

    final = json.loads(json.dumps(baseline))
    v08_contract_path = workspace / f"{PROJECT_REL}/contracts/e4-0-contract-v08-final.json"
    v08_seal_path = workspace / f"{PROJECT_REL}/seals/e4-0-contract-v08-seal.json"
    v08_audit_path = workspace / f"{PROJECT_REL}/audits/e4-0-track-e/track-e-postseal-receipt-v08.json"
    v08_contract_bytes, v08_contract_sha = sha256_file(v08_contract_path)
    v08_seal_bytes, v08_seal_sha = sha256_file(v08_seal_path)
    v08_audit_bytes, v08_audit_sha = sha256_file(v08_audit_path)
    if (v08_contract_bytes != V08_CONTRACT_BYTES or v08_contract_sha != V08_CONTRACT_SHA256
            or v08_seal_bytes != V08_SEAL_BYTES or v08_seal_sha != V08_SEAL_SHA256
            or v08_audit_bytes != V08_AUDIT_BYTES or v08_audit_sha != V08_AUDIT_SHA256):
        raise RuntimeError("sealed v08 immediate predecessor identity changed")
    v08_seal = json.loads(v08_seal_path.read_text(encoding="utf-8"))
    v08_audit = json.loads(v08_audit_path.read_text(encoding="utf-8"))
    v08_contract = json.loads(v08_contract_path.read_text(encoding="utf-8"))
    if (v08_contract.get("contract_id") != "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V08"
            or v08_contract.get("status") != "SEALED"
            or v08_seal.get("seal_id") != "FAS_E4_0_CONTRACT_V08_SEAL"
            or v08_seal.get("root_sha256") != V08_ROOT_SHA256
            or v08_audit.get("pass") is not True
            or v08_audit.get("status") != "E4_0_TRACK_E_POSTSEAL_PASS_V08_SEAL_ROOT_AND_MEMBERS_RECOMPUTED"
            or v08_audit.get("final_seal", {}).get("root_sha256") != V08_ROOT_SHA256):
        raise RuntimeError("sealed v08 predecessor root/status/audit mismatch")
    final["contract_id"] = "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V16"
    final["status"] = "SEALED"
    final["supersedes"] = {
        "contract": {
            "contract_id": "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V11",
            "path": v11_identity["contract"]["path"],
            "bytes": V11_CONTRACT_BYTES,
            "sha256": V11_CONTRACT_SHA256,
        },
        "seal": {
            "seal_id": "FAS_E4_0_CONTRACT_V11_SEAL",
            "path": v11_identity["seal"]["path"],
            "manifest_bytes": V11_SEAL_BYTES,
            "manifest_sha256": V11_SEAL_SHA256,
            "root_sha256": V11_SEAL_ROOT_SHA256,
            "contract_member_artifact_id": "E4_0_CONTRACT_V11_FINAL",
        },
    }
    final["finalized_utc"] = datetime.now(timezone.utc).isoformat()
    design = final["design_inputs"]
    for key in tuple(design):
        if key.startswith(("implementation_source_map_v03_", "implementation_source_map_v04_", "implementation_source_map_v05_", "implementation_source_map_v06_", "implementation_source_map_v07_", "implementation_source_map_v08_", "implementation_source_map_v09_", "implementation_source_map_v10_", "implementation_source_map_v15_", "implementation_source_map_v16_")):
            design.pop(key, None)
    design["implementation_source_map_v16_path"] = MAP_REL
    design["implementation_source_map_v16_sha256"] = map_sha
    design["implementation_source_map_v16_bytes"] = map_bytes
    final.pop("implementation_sources_not_yet_bound", None)
    final.pop("draft_blockers_before_freeze", None)
    final["implementation_sources"] = implementation_source_projection(
        sources, {"path": MAP_REL, "bytes": map_bytes, "sha256": map_sha}
    )
    final["source_test_receipts"] = receipts
    final["finalization"] = {
        "immutable_baseline_contract_path": BASELINE_REL, "immutable_baseline_contract_bytes": baseline_bytes,
        "immutable_baseline_contract_sha256": baseline_sha, "source_map_path": MAP_REL,
        "source_map_bytes": map_bytes, "source_map_sha256": map_sha,
        "source_closure_entry_count": len(sources), "source_test_receipt_count": len(receipts),
        "execution_authorization_conferred": False,
    }
    require_scientific_invariance(final, baseline)
    if any(value is not False for value in final["authorization"].values()):
        raise RuntimeError("contract authorization must remain false")
    if any(value is not False for value in final["execution_identity"].values()):
        raise RuntimeError("execution identity must remain false")
    stop_rel = f"{PROJECT_REL}/audits/e4-0-auth-issuer-v08/online-parity-precontact-stop-v01.json"
    bindings_rel = f"{PROJECT_REL}/audits/e4-0-auth-issuer-v08/online-parity-bindings-v01.json"
    wddm_rel = f"{PROJECT_REL}/audits/e4-0-execution/wddm-gpu-lease-preflight-v02.json"
    stop = json.loads((workspace / stop_rel).read_text(encoding="utf-8"))
    stop_size, stop_sha = sha256_file(workspace / stop_rel)
    bindings_size, bindings_sha = sha256_file(workspace / bindings_rel)
    wddm_size, wddm_sha = sha256_file(workspace / wddm_rel)
    if (stop_size != V08_STOP_BYTES or stop_sha != V08_STOP_SHA256
            or bindings_size != V08_BINDINGS_BYTES or bindings_sha != V08_BINDINGS_SHA256
            or wddm_size != WDDM_BYTES or wddm_sha != WDDM_SHA256):
        raise RuntimeError("v08 stop or WDDM diagnostic identity changed")
    if (stop.get("status") != "E4_0_V08_AUTHORIZATION_STOP_POPULATION_AUDIT_SCHEMA_MISMATCH"
            or stop.get("stop_class") != "PRECONTACT_AUTHORIZATION_VERIFIER_SCHEMA_MISMATCH"
            or stop.get("authorization_output_written") is not False
            or stop.get("authorization_output_exists") is not False
            or stop.get("tokenizer_contact") is not False
            or stop.get("model_contact") is not False
            or stop.get("cuda_initialized") is not False
            or stop.get("gpu_lease_acquired") is not False
            or stop.get("feature_cache_created") is not False
            or stop.get("labels_opened") is not False):
        raise RuntimeError("v08 authorization stop is not the preserved no-contact stop")
    wddm = json.loads((workspace / wddm_rel).read_text(encoding="utf-8"))
    if (wddm.get("status") != "PNOM_SUPPORTED_TYPE_C_PROCESS_ACTIVE"
            or wddm.get("total_gpu_memory_claimed") is not False
            or wddm.get("gpu_lease_acquired") is not False
            or wddm.get("model_contact") is not False
            or wddm.get("tokenizer_contact") is not False
            or wddm.get("cuda_initialized_by_this_task") is not False
            or wddm.get("feature_cache_created") is not False
            or wddm.get("labels_opened") is not False):
        raise RuntimeError("WDDM diagnostic is not the read-only no-contact receipt")
    preseal_history = {
        "first_source_map": (f"{PROJECT_REL}/audits/e4-0-track-e/history/E4-0-IMPLEMENTATION-SOURCE-MAP-v07-first-build.md", V08_FIRST_MAP_BYTES, V08_FIRST_MAP_SHA256),
        "corrected_source_map_audit_stop": (f"{PROJECT_REL}/audits/e4-0-track-e/history/E4-0-IMPLEMENTATION-SOURCE-MAP-v07-predecessor-track-audit-stop.md", V08_AUDIT_STOP_MAP_BYTES, V08_AUDIT_STOP_MAP_SHA256),
        "preseal_stop_receipt": (f"{PROJECT_REL}/audits/e4-0-track-e/history/track-e-preseal-stop-v08-v01.json", V08_PRESEAL_STOP_BYTES, V08_PRESEAL_STOP_SHA256),
        "preseal_candidate_contract": (f"{PROJECT_REL}/audits/e4-0-track-e/history/e4-0-contract-v08-preseal-candidate-v01.json", V08_PRESEAL_CANDIDATE_BYTES, V08_PRESEAL_CANDIDATE_SHA256),
    }
    for name, (rel, expected_bytes, expected_sha) in preseal_history.items():
        actual_bytes, actual_sha = sha256_file(workspace / rel)
        if actual_bytes != expected_bytes or actual_sha != expected_sha:
            raise RuntimeError(f"preserved v08 preseal attempt changed: {name}")
        preseal_history[name] = {"path": rel, "bytes": actual_bytes, "sha256": actual_sha}
    preseal_stop = json.loads((workspace / preseal_history["preseal_stop_receipt"]["path"]).read_text(encoding="utf-8"))
    if preseal_stop.get("status") != "E4_0_TRACK_E_PRESEAL_STOP_MISMATCHES_RECORDED_V08":
        raise RuntimeError("preserved v08 preseal stop receipt has an unexpected status")
    preseal_history["preseal_stop_receipt"]["status"] = preseal_stop["status"]
    v09_map_rel = f"{PROJECT_REL}/plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v08.md"
    v09_contract_rel = f"{PROJECT_REL}/contracts/e4-0-contract-v09-final.json"
    v09_preseal_rel = f"{PROJECT_REL}/audits/e4-0-track-e/track-e-preseal-receipt-v09.json"
    v09_map_path, v09_contract_path, v09_preseal_path = (
        workspace / v09_map_rel, workspace / v09_contract_rel, workspace / v09_preseal_rel)
    v09_map_bytes, v09_map_sha = sha256_file(v09_map_path)
    v09_contract_bytes, v09_contract_sha = sha256_file(v09_contract_path)
    v09_preseal_bytes, v09_preseal_sha = sha256_file(v09_preseal_path)
    v09_contract = json.loads(v09_contract_path.read_text(encoding="utf-8"))
    v09_preseal = json.loads(v09_preseal_path.read_text(encoding="utf-8"))
    if (v09_map_bytes != V09_MAP_BYTES or v09_map_sha != V09_MAP_SHA256
            or v09_contract_bytes != V09_CONTRACT_BYTES or v09_contract_sha != V09_CONTRACT_SHA256
            or v09_preseal_bytes != V09_PRESEAL_BYTES or v09_preseal_sha != V09_PRESEAL_SHA256
            or v09_preseal.get("status") != "E4_0_TRACK_E_PRESEAL_STOP_MISMATCHES_RECORDED_V09"
            or v09_preseal.get("pass") is not False or v09_preseal.get("final_seal") is not None
            or v09_preseal.get("population_truth_files_opened") is not False
            or v09_preseal.get("template_or_joint_truth_opened") is not False):
        raise RuntimeError("preserved v09 preseal attempt identity or no-contact disposition differs")
    for stop_key, required_status in (
            ("preserved_v07_authorization_stop", "PRECONTACT_STOP"),
            ("preserved_v08_authorization_stop", "E4_0_V08_AUTHORIZATION_STOP_POPULATION_AUDIT_SCHEMA_MISMATCH")):
        preserved_stop = v09_preseal.get(stop_key)
        if (not isinstance(preserved_stop, dict)
                or preserved_stop.get("status") != required_status
                or any(preserved_stop.get(key) is not False for key in (
                    "authorization_written", "tokenizer_contact", "model_contact", "cuda_initialized",
                    "gpu_lease_acquired", "feature_cache_created", "labels_opened"))):
            raise RuntimeError(f"preserved v09 nested stop is not the exact no-contact stop: {stop_key}")
    final["engineering_amendment"] = {
        "amendment_kind": "VERSIONED_PRESEAL_SCHEMA_AND_LINEAGE_AUDIT_REPAIR",
        "changed_scientific_fields": [],
        "scientific_baseline": {
            "contract_id": "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V06",
            "contract_sha256": baseline_sha,
            "seal_root_sha256": V06_ROOT_SHA256,
            "contract_path": BASELINE_REL,
            "contract_bytes": baseline_bytes,
            "seal_id": "FAS_E4_0_CONTRACT_V06_SEAL",
            "seal_manifest_sha256": V06_SEAL_SHA256,
            "seal_manifest_bytes": 35340,
        },
        "immediate_predecessor": {
            "contract_id": "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V09",
            "contract_path": v09_contract_rel, "contract_bytes": v09_contract_bytes,
            "contract_sha256": v09_contract_sha,
            "source_map_path": v09_map_rel, "source_map_bytes": v09_map_bytes,
            "source_map_sha256": v09_map_sha,
            "preseal_receipt_path": v09_preseal_rel, "preseal_receipt_bytes": v09_preseal_bytes,
            "preseal_receipt_sha256": v09_preseal_sha,
            "preseal_status": v09_preseal["status"],
        },
        "last_sealed_predecessor": {
            "contract": {"path": f"{PROJECT_REL}/contracts/e4-0-contract-v08-final.json",
                         "bytes": v08_contract_bytes, "sha256": v08_contract_sha,
                         "contract_id": v08_contract["contract_id"]},
            "seal": {"path": f"{PROJECT_REL}/seals/e4-0-contract-v08-seal.json",
                     "bytes": v08_seal_bytes, "sha256": v08_seal_sha,
                     "seal_id": v08_seal["seal_id"], "root_sha256": V08_ROOT_SHA256},
            "postseal_audit": {"path": f"{PROJECT_REL}/audits/e4-0-track-e/track-e-postseal-receipt-v08.json",
                               "bytes": v08_audit_bytes, "sha256": v08_audit_sha,
                               "status": v08_audit["status"], "root_sha256": V08_ROOT_SHA256},
        },
        "failed_v09_preseal_attempt": {
            "source_map": {"path": v09_map_rel, "bytes": v09_map_bytes, "sha256": v09_map_sha},
            "contract": {"path": v09_contract_rel, "bytes": v09_contract_bytes, "sha256": v09_contract_sha},
            "preseal_receipt": {"path": v09_preseal_rel, "bytes": v09_preseal_bytes,
                                "sha256": v09_preseal_sha, "status": v09_preseal["status"]},
            "issues": v09_preseal["issues"], "pass": False, "final_seal": None,
            "population_truth_files_opened": False, "template_or_joint_truth_opened": False,
            "authorization_written": None, "tokenizer_contact": None, "model_contact": None,
            "cuda_initialized": None, "gpu_lease_acquired": None,
            "feature_cache_created": None, "labels_opened": None,
        },
        "historical_v07_lineage": {
            "immediate_predecessor": v09_contract["engineering_amendment"]["historical_v07_lineage"]["immediate_predecessor"],
            "failed_v07_authorization_attempt": v09_contract["engineering_amendment"]["historical_v07_lineage"]["failed_v07_authorization_attempt"],
        },
        "failed_v08_authorization_attempt": v09_contract["engineering_amendment"]["failed_v08_authorization_attempt"],
        "failed_v08_preseal_attempts": v09_contract["engineering_amendment"]["failed_v08_preseal_attempts"],
        "failed_v06_parity_attempt": v09_contract["engineering_amendment"]["failed_v06_parity_attempt"],
        "inherited_population": v09_contract["engineering_amendment"]["inherited_population"],
        "inherited_parity_panel": v09_contract["engineering_amendment"]["inherited_parity_panel"],
        "wddm_gpu_lease_preflight": v09_contract["engineering_amendment"]["wddm_gpu_lease_preflight"],
        "scope": "The v10 update preserves the v06 scientific object, v08 last-sealed state, and v09 failed-preseal history. It corrects only the source-map/auditor receipt identity registry and contract lineage representation identified by the v09 independent preseal stop; the WDDM lease classification and all scientific fields remain unchanged. No E4 authorization is granted.",
    }
    amendment = json.loads(json.dumps(v11_contract["engineering_amendment"]))
    amendment["amendment_kind"] = "VERSIONED_TRANSITIVE_SEAL_MEMBER_INVENTORY_REPAIR_V08"
    v11_contract_binding = {
        "path": v11_identity["contract"]["path"], "bytes": V11_CONTRACT_BYTES,
        "sha256": V11_CONTRACT_SHA256, "contract_id": v11_contract["contract_id"],
    }
    v11_seal_binding = {
        "path": v11_identity["seal"]["path"], "bytes": V11_SEAL_BYTES,
        "sha256": V11_SEAL_SHA256, "seal_id": v11_seal["seal_id"],
        "root_sha256": V11_SEAL_ROOT_SHA256,
    }
    amendment["immediate_predecessor"] = {
        "contract": v11_contract_binding,
        "source_map": {"path": v11_identity["map"]["path"], "bytes": V11_MAP_BYTES,
                       "sha256": V11_MAP_SHA256},
        "preseal_receipt": {"path": v11_identity["preseal"]["path"],
                             "bytes": V11_PRESEAL_BYTES, "sha256": V11_PRESEAL_SHA256,
                             "status": v11_preseal["status"]},
        "seal": v11_seal_binding,
    }
    amendment["last_sealed_predecessor"] = {
        "contract": v11_contract_binding, "seal": v11_seal_binding,
    }
    contact_keys = ("authorization_written", "tokenizer_contact", "model_contact", "cuda_initialized",
                    "gpu_lease_acquired", "feature_cache_created", "labels_opened")
    amendment["failed_v11_postseal_attempt"] = {
        "receipt": {**v11_identity["postseal"], "status": v11_stop["status"]},
        "issues": list(v11_stop["issues"]), "pass": False,
        "final_seal": v11_stop["final_seal"],
        "receipt_contact_fields": {key: None for key in contact_keys},
        **{key: False for key in contact_keys},
    }
    ancestors = [
        {"artifact_id": "E4_0_CONTRACT_V06_SCIENTIFIC_BASELINE", "path": f"{PROJECT_REL}/contracts/e4-0-contract-v06-final.json", "bytes": 43208, "sha256": "ea4f11cec5d65a3be7716c77febf5d448d8ebf1a5a4049aee5d25d51c0c50958"},
        {"artifact_id": "E4_0_CONTRACT_V06_BASELINE_SEAL", "path": f"{PROJECT_REL}/seals/e4-0-contract-v06-seal.json", "bytes": 35340, "sha256": "799d1535a16ea6fbf2269206443addf96736ef8a70ca5ab3373cdd5e6a44605c"},
        {"artifact_id": "E4_0_CONTRACT_V07_SUPERSEDED", "path": f"{PROJECT_REL}/contracts/e4-0-contract-v07-final.json", "bytes": 48881, "sha256": "33b56e95cbf083036f436b5496c2db3c0c052bacfdce593869a6f4aa3125a2d7"},
        {"artifact_id": "E4_0_CONTRACT_V07_SEAL_SUPERSEDED", "path": f"{PROJECT_REL}/seals/e4-0-contract-v07-seal.json", "bytes": 52723, "sha256": "22e2d05255a87334d27713d222fc4023fd1cac61dafc4264c5de434bbf4c71ef"},
        {"artifact_id": "E4_0_CONTRACT_V08_SUPERSEDED", "path": f"{PROJECT_REL}/contracts/e4-0-contract-v08-final.json", "bytes": 54286, "sha256": "ec17befa2a65e0da589ee51792cde3c028e900aa919179b2c9c3365cc20c3e9b"},
        {"artifact_id": "E4_0_CONTRACT_V08_SEAL_SUPERSEDED", "path": f"{PROJECT_REL}/seals/e4-0-contract-v08-seal.json", "bytes": 68666, "sha256": "238d1fdb46ba3d8a9de1ae90e41a9b3c455ba65661bc98e8fe6fa5d21e3d3156"},
        {"artifact_id": "E4_0_CONTRACT_V10_SUPERSEDED", "path": f"{PROJECT_REL}/contracts/e4-0-contract-v10-final.json", "bytes": 66628, "sha256": "c00e140c4cb503717cbf0aa2515f613fde86ac2b81d24a9819d785e9ff959369"},
        {"artifact_id": "E4_0_CONTRACT_V10_SEAL_SUPERSEDED", "path": f"{PROJECT_REL}/seals/e4-0-contract-v10-seal.json", "bytes": 84494, "sha256": "2e6372ba6d34ef4e2c309abd26b857cd69e3a982e3a78398a099c708e9207efa"},
        {"artifact_id": "E4_0_CONTRACT_V11_SUPERSEDED", "path": f"{PROJECT_REL}/contracts/e4-0-contract-v11-final.json", "bytes": V11_CONTRACT_BYTES, "sha256": V11_CONTRACT_SHA256},
        {"artifact_id": "E4_0_CONTRACT_V11_SEAL_SUPERSEDED", "path": f"{PROJECT_REL}/seals/e4-0-contract-v11-seal.json", "bytes": V11_SEAL_BYTES, "sha256": V11_SEAL_SHA256},
    ]
    amendment["transitive_seal_members"] = ancestors
    amendment["scope"] = "The v12 update preserves the v06 scientific object and all v11/v10/v09/v08/v07 lineage. It corrects only the v11 contract sealer's transitive member inventory by adding the exact v08 superseded contract and seal entries identified by the independent v11 postseal audit. A synthetic closure regression derives and checks all sealed ancestors from v06 through v11. No scientific field or execution boundary changes; no E4 stage authorization is granted."
    prior_v12_lineage = json.loads(json.dumps(amendment))
    failed_v12 = {
        "source_map": {"path": v12_identity["map"]["path"], "bytes": V12_MAP_BYTES, "sha256": V12_MAP_SHA256},
        "contract": {"path": v12_identity["contract"]["path"], "bytes": V12_CONTRACT_BYTES, "sha256": V12_CONTRACT_SHA256},
        "preseal_receipt": {"path": v12_identity["preseal"]["path"], "bytes": V12_PRESEAL_BYTES,
                             "sha256": V12_PRESEAL_SHA256, "status": v12_preseal["status"]},
        "issues": list(v12_preseal["issues"]), "pass": False, "final_seal": None,
        "population_truth_files_opened": False, "template_or_joint_truth_opened": False,
        "authorization_written": False, "tokenizer_contact": False, "model_contact": False,
        "cuda_initialized": False, "gpu_lease_acquired": False, "feature_cache_created": False,
        "labels_opened": False,
    }
    contract_v12 = {"contract_id": v12_contract["contract_id"], "path": v12_identity["contract"]["path"],
                    "bytes": V12_CONTRACT_BYTES, "sha256": V12_CONTRACT_SHA256}
    map_v12 = {"path": v12_identity["map"]["path"], "bytes": V12_MAP_BYTES, "sha256": V12_MAP_SHA256}
    preseal_v12 = {"path": v12_identity["preseal"]["path"], "bytes": V12_PRESEAL_BYTES,
                   "sha256": V12_PRESEAL_SHA256, "status": v12_preseal["status"]}
    amendment = {
        "amendment_kind": "VERSIONED_TRACK_E_AUDITOR_EXPECTATION_SCHEMA_REPAIR",
        "immediate_predecessor": {"contract": contract_v12, "source_map": map_v12, "preseal_receipt": preseal_v12},
        "last_sealed_predecessor": {
            "contract": v11_contract_binding,
            "seal": v11_seal_binding,
        },
        "prior_v12_lineage": prior_v12_lineage,
        "failed_v12_preseal_attempt": failed_v12,
        "failed_v12_map_build_attempt": {
            "source_map": failed_v12_map_binding,
            "issues": [
                "map title identifies v11 despite v12 path",
                "builder terminal status labels output SOURCE_MAP_V11_CREATED_UNAUTHORIZED",
                "inherited Input Path role repeats Preserved v06 predecessor input prefix",
            ],
            "pass": False, "final_seal": None,
            "authorization_written": False, "tokenizer_contact": False, "model_contact": False,
            "cuda_initialized": False, "gpu_lease_acquired": False,
            "feature_cache_created": False, "labels_opened": False,
        },
        "scope": "The v15 update preserves the v06 scientific object and exact v12 candidate lineage. It repairs the independent Track E auditor's expected v11 final_seal schema and corrects the v12 source-map heading, build status, and inherited input-role wording in a new v15 map. The failed v12 preseal and map-build attempts remain bound with no contact. No scientific field or execution boundary changes; no E4 stage authorization is granted.",
    }
    v15_map_path = workspace / V15_MAP_REL
    v15_contract_path = workspace / V15_CONTRACT_REL
    v15_preseal_path = workspace / V15_PRESEAL_REL
    for path, expected in (
        (v15_map_path, (V15_MAP_BYTES, V15_MAP_SHA256)),
        (v15_contract_path, (V15_CONTRACT_BYTES, V15_CONTRACT_SHA256)),
        (v15_preseal_path, (V15_PRESEAL_BYTES, V15_PRESEAL_SHA256)),
    ):
        if sha256_file(path) != expected:
            raise RuntimeError(f"preserved failed v15 candidate identity changed: {path}")
    v15_contract = json.loads(v15_contract_path.read_text(encoding="utf-8"))
    v15_preseal = json.loads(v15_preseal_path.read_text(encoding="utf-8"))
    absent_contact = ("authorization_written", "tokenizer_contact", "model_contact", "cuda_initialized",
                      "gpu_lease_acquired", "feature_cache_created", "labels_opened")
    if (v15_contract.get("contract_id") != "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V15"
            or v15_contract.get("status") != "SEALED"
            or v15_preseal.get("status") != V15_PRESEAL_STATUS
            or v15_preseal.get("issues") != V15_PRESEAL_ISSUES
            or v15_preseal.get("pass") is not False or v15_preseal.get("final_seal") is not None
            or any(v15_preseal.get(key) is not False for key in (
                "population_truth_files_opened", "template_or_joint_truth_opened"))
            or any(key in v15_preseal for key in absent_contact)):
        raise RuntimeError("preserved v15 preseal stop is not the exact no-contact three-issue result")
    v16_v02_bindings = (
        (V16_V02_MAP_REL, V16_V02_MAP_BYTES, V16_V02_MAP_SHA256),
        (V16_V02_CONTRACT_REL, V16_V02_CONTRACT_BYTES, V16_V02_CONTRACT_SHA256),
        (V16_V02_PRESEAL_REL, V16_V02_PRESEAL_BYTES, V16_V02_PRESEAL_SHA256),
    )
    for rel, size, sha in v16_v02_bindings:
        if sha256_file(workspace / rel) != (size, sha):
            raise RuntimeError(f"preserved failed v16-v02 artifact identity changed: {rel}")
    v16_v02_contract = json.loads((workspace / V16_V02_CONTRACT_REL).read_text(encoding="utf-8"))
    v16_v02_stop = json.loads((workspace / V16_V02_PRESEAL_REL).read_text(encoding="utf-8"))
    if (v16_v02_contract.get("contract_id") != "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V16"
            or v16_v02_contract.get("status") != "SEALED"
            or v16_v02_stop.get("status") != V16_V02_PRESEAL_STATUS
            or v16_v02_stop.get("issues") != V16_V02_PRESEAL_ISSUES
            or v16_v02_stop.get("pass") is not False or v16_v02_stop.get("final_seal") is not None
            or v16_v02_stop.get("contract") != {
                "path": V16_V02_CONTRACT_REL, "bytes": V16_V02_CONTRACT_BYTES,
                "sha256": V16_V02_CONTRACT_SHA256,
            }
            or v16_v02_stop.get("source_map") != {
                "path": V16_V02_MAP_REL, "bytes": V16_V02_MAP_BYTES,
                "sha256": V16_V02_MAP_SHA256,
            }
            or any(v16_v02_stop.get(k) is not False for k in ("population_truth_files_opened", "template_or_joint_truth_opened"))
            or any(k in v16_v02_stop for k in absent_contact)):
        raise RuntimeError("preserved v16-v02 preseal attempt differs from exact no-contact findings")
    v16_v03_bindings = (
        (V16_V03_MAP_REL, V16_V03_MAP_BYTES, V16_V03_MAP_SHA256),
        (V16_V03_CONTRACT_REL, V16_V03_CONTRACT_BYTES, V16_V03_CONTRACT_SHA256),
        (V16_V03_PRESEAL_REL, V16_V03_PRESEAL_BYTES, V16_V03_PRESEAL_SHA256),
    )
    for rel, size, sha in v16_v03_bindings:
        if sha256_file(workspace / rel) != (size, sha):
            raise RuntimeError(f"preserved failed v16-v03 artifact identity changed: {rel}")
    v16_v03_contract = json.loads((workspace / V16_V03_CONTRACT_REL).read_text(encoding="utf-8"))
    v16_v03_stop = json.loads((workspace / V16_V03_PRESEAL_REL).read_text(encoding="utf-8"))
    if (v16_v03_contract.get("contract_id") != "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V16"
            or v16_v03_contract.get("status") != "SEALED"
            or v16_v03_stop.get("status") != V16_V03_PRESEAL_STATUS
            or v16_v03_stop.get("issues") != V16_V03_PRESEAL_ISSUES
            or v16_v03_stop.get("pass") is not False
            or v16_v03_stop.get("final_seal") is not None
            or v16_v03_stop.get("contract") != {"path": V16_V03_CONTRACT_REL,
                "bytes": V16_V03_CONTRACT_BYTES, "sha256": V16_V03_CONTRACT_SHA256}
            or v16_v03_stop.get("source_map") != {"path": V16_V03_MAP_REL,
                "bytes": V16_V03_MAP_BYTES, "sha256": V16_V03_MAP_SHA256}
            or any(v16_v03_stop.get(k) is not False for k in (
                "population_truth_files_opened", "template_or_joint_truth_opened"))
            or any(k in v16_v03_stop for k in absent_contact)):
        raise RuntimeError("preserved v16-v03 preseal attempt differs from exact no-contact scope stop")
    if (workspace / f"{PROJECT_REL}/seals/e4-0-contract-v16-v02-seal.json").exists():
        raise RuntimeError("failed v16-v03 candidate unexpectedly has a contract seal")
    if (workspace / f"{PROJECT_REL}/seals/e4-0-contract-v16-seal.json").exists():
        raise RuntimeError("failed v16-v02 candidate unexpectedly has a contract seal")
    for rel, size, sha in (
        (V16_V04_MAP_REL, V16_V04_MAP_BYTES, V16_V04_MAP_SHA256),
        (V16_V04_CONTRACT_REL, V16_V04_CONTRACT_BYTES, V16_V04_CONTRACT_SHA256),
        (V16_V04_PRESEAL_REL, V16_V04_PRESEAL_BYTES, V16_V04_PRESEAL_SHA256),
        (V16_V04_SEALER_REL, V16_V04_SEALER_BYTES, V16_V04_SEALER_SHA256),
        (V16_V04_SEAL_STOP_REL, V16_V04_SEAL_STOP_BYTES, V16_V04_SEAL_STOP_SHA256),
    ):
        if sha256_file(workspace / rel) != (size, sha):
            raise RuntimeError(f"preserved v16-v04 failed-seal artifact identity changed: {rel}")
    v16_v04_contract = json.loads((workspace / V16_V04_CONTRACT_REL).read_text(encoding="utf-8"))
    v16_v04_stop = json.loads((workspace / V16_V04_SEAL_STOP_REL).read_text(encoding="utf-8"))
    if (v16_v04_contract.get("contract_id") != "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V16"
            or v16_v04_contract.get("status") != "SEALED"
            or v16_v04_stop.get("status") != V16_V04_SEAL_STOP_STATUS
            or v16_v04_stop.get("mode") != "SEAL"
            or v16_v04_stop.get("pass") is not False
            or v16_v04_stop.get("diagnostic", {}).get("message") != V16_V04_SEAL_STOP_DIAGNOSTIC
            or v16_v04_stop.get("contract") != {"path": V16_V04_CONTRACT_REL,
                "bytes": V16_V04_CONTRACT_BYTES, "sha256": V16_V04_CONTRACT_SHA256}
            or v16_v04_stop.get("source_map") != {"path": V16_V04_MAP_REL,
                "bytes": V16_V04_MAP_BYTES, "sha256": V16_V04_MAP_SHA256}
            or v16_v04_stop.get("preseal_receipt") != {"path": V16_V04_PRESEAL_REL,
                "bytes": V16_V04_PRESEAL_BYTES, "sha256": V16_V04_PRESEAL_SHA256}
            or v16_v04_stop.get("sealer_source") != {"path": V16_V04_SEALER_REL,
                "bytes": V16_V04_SEALER_BYTES, "sha256": V16_V04_SEALER_SHA256}
            or v16_v04_stop.get("final_seal") is not None
            or any(v16_v04_stop.get(k) is not False for k in (
                "population_truth_files_opened", "template_or_joint_truth_opened", "authorization_written",
                "model_contact", "tokenizer_contact", "cuda_initialized", "gpu_lease_acquired",
                "feature_cache_created", "labels_opened"))):
        raise RuntimeError("preserved v16-v04 seal stop is not the exact no-contact duplicate-member failure")
    if (workspace / f"{PROJECT_REL}/seals/e4-0-contract-v16-v03-seal.json").exists():
        raise RuntimeError("failed v16-v04 candidate unexpectedly has a contract seal")
    v14_contract = json.loads((workspace / V14_CONTRACT_REL).read_text(encoding="utf-8"))
    amendment = json.loads(json.dumps(v14_contract["engineering_amendment"]))
    amendment["amendment_kind"] = "VERSIONED_SEAL_MEMBER_DEDUPLICATION_REPAIR_V16_V05"
    amendment["immediate_predecessor"] = {
        "contract": {"path": V15_CONTRACT_REL, "bytes": V15_CONTRACT_BYTES,
                     "sha256": V15_CONTRACT_SHA256, "contract_id": v15_contract["contract_id"]},
        "source_map": {"path": V15_MAP_REL, "bytes": V15_MAP_BYTES, "sha256": V15_MAP_SHA256},
        "preseal_receipt": {"path": V15_PRESEAL_REL, "bytes": V15_PRESEAL_BYTES,
                            "sha256": V15_PRESEAL_SHA256, "status": V15_PRESEAL_STATUS},
    }
    amendment["failed_v15_preseal_attempt"] = {
        "source_map": v15_preseal["source_map"],
        "contract": v15_preseal["contract"],
        "preseal_receipt": {"path": V15_PRESEAL_REL, "bytes": V15_PRESEAL_BYTES,
                            "sha256": V15_PRESEAL_SHA256, "status": V15_PRESEAL_STATUS},
        "issues": list(V15_PRESEAL_ISSUES), "pass": False, "final_seal": None,
        "population_truth_files_opened": False, "template_or_joint_truth_opened": False,
    }
    amendment["failed_v16_map_finalization_attempt"] = {
        "source_map": {"path": V16_FIRST_MAP_REL, "bytes": V16_FIRST_MAP_BYTES,
                       "sha256": V16_FIRST_MAP_SHA256},
        "finalization_stop_receipt": {"path": V16_FINALIZATION_STOP_REL,
            "bytes": V16_FINALIZATION_STOP_BYTES, "sha256": V16_FINALIZATION_STOP_SHA256,
            "status": V16_FINALIZATION_STOP_STATUS},
        "contract_candidate_written": False, "seal_written": False,
        "model_contact": False, "tokenizer_contact": False, "cuda_initialized": False,
        "labels_opened": False,
    }
    amendment["failed_v14_preseal_attempt"] = V14_FAILED_PRESEAL_ATTEMPT
    amendment["failed_v16_v02_preseal_attempt"] = {
        "source_map": {"path": V16_V02_MAP_REL, "bytes": V16_V02_MAP_BYTES, "sha256": V16_V02_MAP_SHA256},
        "contract": {"path": V16_V02_CONTRACT_REL, "bytes": V16_V02_CONTRACT_BYTES, "sha256": V16_V02_CONTRACT_SHA256},
        "preseal_receipt": {"path": V16_V02_PRESEAL_REL, "bytes": V16_V02_PRESEAL_BYTES,
                            "sha256": V16_V02_PRESEAL_SHA256, "status": V16_V02_PRESEAL_STATUS},
        "issues": list(V16_V02_PRESEAL_ISSUES), "pass": False, "final_seal": None,
        "population_truth_files_opened": False, "template_or_joint_truth_opened": False,
    }
    amendment["failed_v16_v03_preseal_attempt"] = {
        "source_map": {"path": V16_V03_MAP_REL, "bytes": V16_V03_MAP_BYTES, "sha256": V16_V03_MAP_SHA256},
        "contract": {"path": V16_V03_CONTRACT_REL, "bytes": V16_V03_CONTRACT_BYTES, "sha256": V16_V03_CONTRACT_SHA256},
        "preseal_receipt": {"path": V16_V03_PRESEAL_REL, "bytes": V16_V03_PRESEAL_BYTES,
                            "sha256": V16_V03_PRESEAL_SHA256, "status": V16_V03_PRESEAL_STATUS},
        "issues": list(V16_V03_PRESEAL_ISSUES), "pass": False, "final_seal": None,
        "population_truth_files_opened": False, "template_or_joint_truth_opened": False,
    }
    amendment["failed_v16_v04_seal_attempt"] = {
        "contract": {"path": V16_V04_CONTRACT_REL, "bytes": V16_V04_CONTRACT_BYTES, "sha256": V16_V04_CONTRACT_SHA256},
        "source_map": {"path": V16_V04_MAP_REL, "bytes": V16_V04_MAP_BYTES, "sha256": V16_V04_MAP_SHA256},
        "preseal_receipt": {"path": V16_V04_PRESEAL_REL, "bytes": V16_V04_PRESEAL_BYTES, "sha256": V16_V04_PRESEAL_SHA256},
        "sealer_source": {"path": V16_V04_SEALER_REL, "bytes": V16_V04_SEALER_BYTES, "sha256": V16_V04_SEALER_SHA256},
        "stop_receipt": {"path": V16_V04_SEAL_STOP_REL, "bytes": V16_V04_SEAL_STOP_BYTES,
                          "sha256": V16_V04_SEAL_STOP_SHA256, "status": V16_V04_SEAL_STOP_STATUS},
        "diagnostic": {"exception_class": "RuntimeError", "message": V16_V04_SEAL_STOP_DIAGNOSTIC},
        "pass": False, "final_seal": None,
        "population_truth_files_opened": False, "template_or_joint_truth_opened": False,
        "authorization_written": False, "model_contact": False, "tokenizer_contact": False,
        "cuda_initialized": False, "gpu_lease_acquired": False, "feature_cache_created": False,
        "labels_opened": False,
    }
    amendment["scope"] = V16_SCOPE
    final["engineering_amendment"] = amendment
    require_scientific_invariance(final, baseline)
    return final


def main() -> int:
    workspace = Path(__file__).resolve().parents[4]
    output = workspace / OUTPUT_REL
    safe_output_path(output, workspace)
    contract = build_final_contract(workspace)
    encoded = (json.dumps(contract, ensure_ascii=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
    print(json.dumps({"status": "FINAL_CONTRACT_CREATED_UNAUTHORIZED", "path": OUTPUT_REL,
                      "bytes": len(encoded), "sha256": hashlib.sha256(encoded).hexdigest(),
                      "source_receipts": len(contract["source_test_receipts"])}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
