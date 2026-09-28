"""Create one immutable, stage-scoped E4-0 authorization from verified bindings.

This v16 successor binds the v16 contract to the exact failed v15 candidate and preserves
the complete v06-v11 sealed-ancestor inventory. It retains the
population-audit schema normalization and existing truth/resource gates. This module is
model-free and does not open population labels, import inference runtimes, or
initialize CUDA.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Mapping


SCHEMA = "FAS_E4_0_STAGE_AUTH_V01"
AUTHORIZATION_ID = "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_STAGE_AUTHORIZATION_V01"
CONTRACT_ID = "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V16"
ARTIFACT_SEAL_SCHEMA = "FAS_E4_0_ARTIFACT_SEAL_V01"
CONTRACT_SEAL_ID = "FAS_E4_0_CONTRACT_V16_SEAL"
CONTRACT_MEMBER_ARTIFACT_ID = "E4_0_CONTRACT_V16_FINAL"
CONTRACT_MEMBER_PATH = "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v16-final.json"
GPU_RESERVED_LIMIT_BYTES = 10 * 1024**3
GPU_QUIET_WINDOW_SECONDS = 30
GPU_POLL_INTERVAL_SECONDS = 5
DEFAULT_VALIDITY_SECONDS = 8 * 60 * 60
MAX_VALIDITY_SECONDS = 24 * 60 * 60

PREDECESSOR_ROOTS = {
    "e0_v10_root_sha256": "899a131c09298fdafdcc6771ad01e8982857a1cd47900259800f97dd7bea7ccd",
    "e1_v04_root_sha256": "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03",
    "e2_v07_root_sha256": "a2e2aa76f77904665b9abfa2a22f609c05219d8bc64c537bed41f5c634d1da8a",
    "e3_v02_bundle_root_sha256": "899ff6a61272b86fdf1cd51d8c14100e77185157c242f27fbffe452803a435e1",
}
ROOT_ORDER = (
    "e0_v10_root_sha256",
    "e1_v04_root_sha256",
    "e2_v07_root_sha256",
    "e3_v02_bundle_root_sha256",
    "e4_population_root_sha256",
    "e4_population_audit_root_sha256",
    "e4_parity_panel_root_sha256",
    "e4_parity_receipt_root_sha256",
    "e4_feature_cache_root_sha256",
)
SCOPE_KEYS = (
    "population_generation",
    "tokenizer_contact",
    "model_contact",
    "feature_extraction",
    "evaluation_label_opening",
    "scoring",
    "fitting",
    "e4_a",
    "heldout_template_label_opening",
    "joint_template_label_opening",
)
TRUE_SCOPES = {
    "POPULATION_GENERATION": {"population_generation"},
    "ONLINE_CACHE_PARITY": {"model_contact", "feature_extraction"},
    "FRESH_FEATURE_EXTRACTION": {"model_contact", "feature_extraction"},
    "FRESH_SCORING": {"evaluation_label_opening", "scoring"},
}
BASE_ARTIFACTS = {
    "e4_contract",
    "e4_contract_seal_manifest",
    "e4_contract_audit",
    "e0_seal",
    "e0_audit",
    "e1_seal",
    "e1_audit",
    "e2_seal",
    "e2_audit",
    "e3_seal",
    "e3_audit",
    "representation_abi",
    "model_manifest",
    "tokenizer_manifest",
}
ARTIFACTS_BY_STAGE = {
    "POPULATION_GENERATION": BASE_ARTIFACTS | {
        "e1_inputs", "e1_rows", "e1_terms", "heldout_template_manifest",
        "support_plan", "population_generator",
    },
    "ONLINE_CACHE_PARITY": BASE_ARTIFACTS | {
        "e1_inputs", "e1_rows", "e1_splits", "e1_terms", "e2_cache", "e3_bundle",
        "population_seal", "population_audit", "parity_panel_seal",
        "parity_inputs", "parity_rows", "parity_selection_receipt",
    },
    "FRESH_FEATURE_EXTRACTION": BASE_ARTIFACTS | {
        "population_seal", "population_audit", "parity_panel_seal",
        "parity_receipt_seal", "population_inputs", "population_rows",
    },
    # These source identities are used to derive and check the nine roots, but
    # are deliberately not emitted in a FRESH_SCORING receipt.
    "FRESH_SCORING": BASE_ARTIFACTS | {
        "population_seal", "population_audit", "parity_panel_seal",
        "parity_receipt_seal", "feature_cache_seal",
    },
}
PATH_KEYS = frozenset({
    "model_snapshot", "tokenizer_snapshot", "model_asset_manifest", "tokenizer_asset_manifest",
})
ROOT_FILE_ROLES = {
    "e0_v10_root_sha256": "e0_seal",
    "e1_v04_root_sha256": "e1_seal",
    "e2_v07_root_sha256": "e2_seal",
    "e3_v02_bundle_root_sha256": "e3_seal",
    "e4_population_root_sha256": "population_seal",
    "e4_parity_panel_root_sha256": "parity_panel_seal",
    "e4_parity_receipt_root_sha256": "parity_receipt_seal",
    "e4_feature_cache_root_sha256": "feature_cache_seal",
}
HEX64 = re.compile(r"[0-9a-f]{64}\Z")

# v09 changes only population-audit schema normalization. Authorization lineage
# remains bound to sealed v08; the v06 scientific baseline and v07 execution
# parent identities remain immutable and are never regenerated.
V06_CONTRACT_SHA256 = "ea4f11cec5d65a3be7716c77febf5d448d8ebf1a5a4049aee5d25d51c0c50958"
V06_CONTRACT_SEAL_MANIFEST_SHA256 = "799d1535a16ea6fbf2269206443addf96736ef8a70ca5ab3373cdd5e6a44605c"
V06_CONTRACT_SEAL_ROOT_SHA256 = "7344badf07476d19d9c6228f80d026a112c339e93daa75593e61031f68456e64"
V06_CONTRACT_BYTES = 43208
V06_CONTRACT_SEAL_MANIFEST_BYTES = 35340
V06_CONTRACT_ID = "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V06"
V06_CONTRACT_SEAL_ID = "FAS_E4_0_CONTRACT_V06_SEAL"
V06_CONTRACT_MEMBER_ARTIFACT_ID = "E4_0_CONTRACT_V06_FINAL"
V07_CONTRACT_SHA256 = "33b56e95cbf083036f436b5496c2db3c0c052bacfdce593869a6f4aa3125a2d7"
V07_CONTRACT_BYTES = 48881
V07_CONTRACT_SEAL_MANIFEST_SHA256 = "22e2d05255a87334d27713d222fc4023fd1cac61dafc4264c5de434bbf4c71ef"
V07_CONTRACT_SEAL_MANIFEST_BYTES = 52723
V07_CONTRACT_SEAL_ROOT_SHA256 = "ee7339c3ab04272354b4cae03294c794a6e823fdb1766ad44f71978dfee0c62c"
V07_CONTRACT_ID = "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V07"
V07_CONTRACT_SEAL_ID = "FAS_E4_0_CONTRACT_V07_SEAL"
V07_CONTRACT_MEMBER_ARTIFACT_ID = "E4_0_CONTRACT_V07_FINAL"
V08_CONTRACT_SHA256 = "ec17befa2a65e0da589ee51792cde3c028e900aa919179b2c9c3365cc20c3e9b"
V08_CONTRACT_BYTES = 54286
V08_CONTRACT_ID = "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V08"
V08_CONTRACT_SEAL_SHA256 = "238d1fdb46ba3d8a9de1ae90e41a9b3c455ba65661bc98e8fe6fa5d21e3d3156"
V08_CONTRACT_SEAL_BYTES = 68666
V08_CONTRACT_SEAL_ROOT_SHA256 = "e0093eacd70ce7cbf3b3a19045683ce5a7f4d4413748003e2d8e1446f131478d"
V08_CONTRACT_SEAL_ID = "FAS_E4_0_CONTRACT_V08_SEAL"
V08_CONTRACT_MEMBER_ARTIFACT_ID = "E4_0_CONTRACT_V08_FINAL"
V08_POSTSEAL_AUDIT_SHA256 = "8e2fb068f0ce4acda3d91fe53f4f9b37fab9cffa49a2067ffdd939e95c862898"
V08_POSTSEAL_AUDIT_BYTES = 68220
V08_POSTSEAL_AUDIT_STATUS = "E4_0_TRACK_E_POSTSEAL_PASS_V08_SEAL_ROOT_AND_MEMBERS_RECOMPUTED"
V09_CONTRACT_SHA256 = "f973bbd7d5bebeb6a60b8586060c8c65424deefdfce64ddcfd45246ebdfabd44"
V09_CONTRACT_BYTES = 61414
V09_MAP_SHA256 = "c79306de009e82a5bdd5bd650e64744d115b870c8c4309dd5863a4d7b339b267"
V09_MAP_BYTES = 65000
V09_PRESEAL_SHA256 = "7ee376b87c41f727274f58f72f2db524806206ea216b3c18a8d82843e94d1bf8"
V09_PRESEAL_BYTES = 84023
V10_CONTRACT_SHA256 = "c00e140c4cb503717cbf0aa2515f613fde86ac2b81d24a9819d785e9ff959369"
V10_CONTRACT_BYTES = 66628
V10_CONTRACT_ID = "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V10"
V10_MAP_SHA256 = "6f53cb299ab9aefd0ee3ea7ea485d86f20b6a64acde15ee498a50f3e4efd7945"
V10_MAP_BYTES = 73060
V10_PRESEAL_SHA256 = "dfc41a61d69384a26ea4c743ba27cf84d48f9859827a32cc6c6caab28aa22f83"
V10_PRESEAL_BYTES = 91652
V10_SEAL_SHA256 = "2e6372ba6d34ef4e2c309abd26b857cd69e3a982e3a78398a099c708e9207efa"
V10_SEAL_BYTES = 84494
V10_SEAL_ROOT_SHA256 = "b9eab12e1ff189c6c9fff3d63ea1e11b4f0e7a54d92a2b57accd39adee5ec5b5"
V10_POSTSEAL_V01_SHA256 = "b82b1c6404a293436e99eee5816f0e14fdd1d28b9da2cab6ec419272c56458d0"
V10_POSTSEAL_V01_BYTES = 91693
V10_POSTSEAL_V02_SHA256 = "e4561320636702663836d39f1deee4320d465efbc00feaea0369754a6a32f221"
V10_POSTSEAL_V02_BYTES = 92830
V11_CONTRACT_ID = "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V11"
V11_CONTRACT_SHA256 = "9cefc7cf9ca8f367bceff3c1c9b7e84ab3e15f684326edf94354e33e3d1fb2fd"
V11_CONTRACT_BYTES = 72068
V11_SEAL_ID = "FAS_E4_0_CONTRACT_V11_SEAL"
V11_SEAL_SHA256 = "7f27371f3cb886208ff67ea7a19e2ca51577bfbc74e4f6611ca496ab9c13ebcd"
V11_SEAL_BYTES = 90814
V11_SEAL_ROOT = "dc7ec0731a6f637bd8aa6416bd74aba8e074e8bf0c936a1bda830e79c0afa6c3"
V12_CONTRACT_ID = "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V12"
V12_CONTRACT_SHA256 = "9dee0e26b3eb1fcdbcc7146214745f8d699459bfdd23f15b8532e87cc9da3e75"
V12_CONTRACT_BYTES = 78271
V12_MAP_SHA256 = "61df89861d9540641305cdb0020a7bc95772a8adab529e5fdd62898e4c066930"
V12_MAP_BYTES = 91198
V12_PRESEAL_SHA256 = "4ac87653ae964e3ede95876ba3a9a7a32402672331d1c25f9b41d06725131f24"
V12_PRESEAL_BYTES = 111784
V12_FAILED_MAP_SHA256 = "697a438d99ae8897a3dcb390783ef8ab65c17bd1ffcca16465ffb7f3a4d74073"
V12_FAILED_MAP_BYTES = 100147
V14_CONTRACT_SHA256 = "9a195eaa7cbbdfff79ee9095c283c52bfb2e78baf40608eab86c0435c443b8f8"
V14_CONTRACT_BYTES = 86587
V14_MAP_SHA256 = "40f1d41123dd75093766c01f3e8073f584cf3a7c265d2fba0461ed72ced4fe8f"
V14_MAP_BYTES = 89298
V14_PRESEAL_SHA256 = "d97d00209cc485d80af1d8a7faa0da15cbdf54a79357b13efe9b458ec4d97995"
V14_PRESEAL_BYTES = 112879
V14_PRESEAL_STATUS = "E4_0_TRACK_E_PRESEAL_STOP_MISMATCHES_RECORDED_V14"
V14_PRESEAL_ISSUES = [
    "v14 amendment does not exactly preserve v13 lineage and bind the failed v13 finalizer attempt",
    "source-test receipt track/path/status differs from its registered identity: 'Predecessor Authorization issuer v13': expected ('experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-auth-issuer-v13/source-tests-v01.json', 'PASS_SYNTHETIC_TESTS'), got ('experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-auth-issuer-v13/source-tests-v02.json', 'PASS_SYNTHETIC_TESTS')",
    "source-test receipt track/path/status differs from its registered identity: 'Predecessor Contract tooling v13': expected ('experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/contract-tooling-source-tests-v12.json', 'PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS'), got ('experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/contract-tooling-source-tests-v13.json', 'PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS')",
    "source-test receipt track/path/status differs from its registered identity: 'Contract tooling v14': expected ('experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/contract-tooling-source-tests-v13.json', 'PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS'), got ('experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/contract-tooling-source-tests-v14.json', 'PASS_SYNTHETIC_CONTRACT_AND_SOURCE_MAP_TESTS')",
    "source map must bind exactly one v13 failed-finalization source artifact",
]
V15_CONTRACT_REL = "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v15-final.json"
V15_CONTRACT_SHA256 = "a29963988af2c7d1456e403a1cf219a915d29b2b7f4559b44ef175f60aa1d698"
V15_CONTRACT_BYTES = 95055
V15_MAP_REL = "experiments/fas-frozen-observer-bundle-engineering-v01/plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v15.md"
V15_MAP_SHA256 = "3747444405a905ed8918d7939ce7e968915b02d6ebcee422d588f010d7fe50f1"
V15_MAP_BYTES = 94630
V15_PRESEAL_REL = "experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/track-e-preseal-receipt-v15.json"
V15_PRESEAL_SHA256 = "66b9059a9b92c6711d704d1849bb60158003746b394c8d5bb1ebedb4b2a3113b"
V15_PRESEAL_BYTES = 118505
V15_PRESEAL_STATUS = "E4_0_TRACK_E_PRESEAL_STOP_MISMATCHES_RECORDED_V15"
V15_PRESEAL_ISSUES = [
    "v15 amendment does not exactly preserve v14 lineage and bind its failed-preseal attempt",
    "contract implementation_sources does not exactly bind source-map rows by role",
    "source-test receipt track/path/status differs from its registered identity: 'Predecessor Track E v07 pre-map': expected ('experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/track-e-source-tests-v15.json', 'TRACK_E_SOURCE_TESTS_PASS_V07_PREMAP_SYNTHETIC_AUDITOR'), got ('experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/track-e-source-tests-v14.json', 'TRACK_E_SOURCE_TESTS_PASS_V07_PREMAP_SYNTHETIC_AUDITOR')",
]
V16_AMENDMENT_KIND = "VERSIONED_TRACK_E_PRESEAL_SCHEMA_AND_SOURCE_BINDING_REPAIR_V16"
V16_SCOPE = "The v16 update preserves the v06 scientific object and v11 last sealed predecessor, carries forward the canonical v12-v14 lineage, and binds the exact v15 failed-preseal map, contract, and stop. It corrects only the v15 amendment serialization, exact no-contact stop schema, source-map/implementation-source closure, and the Track E v07 predecessor receipt path. No scientific field or execution boundary changes; no E4 stage authorization is granted."
V15_SCOPE = "The v15 update preserves the v06 scientific object and complete v14/v13/v12 lineage. It corrects only the independent Track E v14 auditor's receipt registry to the exact preserved issuer-v13/tooling-v13 and tooling-v14 receipt identities, corrects the v12 preseal nested contract identity schema, and adds the v13 finalizer source as a frozen input in a new v15 source map. The failed v14 preseal is bound exactly; no scientific field or execution boundary changes; no E4 stage authorization is granted."
V13_MAP_SHA256 = "a06d436c5cee8305ab65a7cb77f34165f48ccdeee932b788a511a70663c47fc6"
V13_MAP_BYTES = 86052
V13_FINALIZER_SHA256 = "03025d1e0e5ed52e7ef3920db0ef780139944fd209fa9d221ca071b42f16ed11"
V13_FINALIZER_BYTES = 52511
V13_STOP_SHA256 = "43e1270f5d395154ab713401558814503dc4fc143048d980447932750fa577dc"
V13_STOP_BYTES = 1658
V13_STOP_STATUS = "E4_0_V13_FINALIZATION_STOP_RECEIPT_STATUS_MISMATCH"
V13_STOP_DIAGNOSTIC = "receipt status mismatch or failure: experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/track-e-source-tests-v20.json"
V11_MAP_SHA256 = "d464e0e4898da33afcab6153f7f7df34be9f2a3f9ec499896ac703807f986b6e"
V11_MAP_BYTES = 82088
V11_PRESEAL_SHA256 = "a3ccc4181717af9a84b2e16fc57a7f8819d0fc646918f6f09f760e8bf2c0392d"
V11_PRESEAL_BYTES = 101751
V11_POSTSEAL_SHA256 = "09822f935ef94c9307f3a9754dc8a408294de0f77832b7ef09f8e47d56272aa9"
V11_POSTSEAL_BYTES = 102930
V06_REFERENCE_AUTHORIZATION_SHA256 = "59d6ed54ca401ce6606cd2f3053a19ded24252c1a725aa53508cb0625a8197aa"
V06_REFERENCE_AUTHORIZATION_BYTES = 9884
V06_INHERITED_ROOTS = {
    "e4_population_root_sha256": "27731b483b8242aaef15ca22b97796b7b305a79db9bbb235765e13dcd9d08967",
    "e4_population_audit_root_sha256": "7dd3eea3133dbed779071fd14e22df06ff5a0ddce994e4446cf4c6ef7b9cbe5a",
    "e4_parity_panel_root_sha256": "6ef00306df0df20ada7b7a86b09567ae46e07f112f66d974d7885e8f1e5d4d95",
}
V06_INHERITED_ARTIFACT_IDENTITIES = {
    "population_seal": ("ad8175710b4f2db9aa6529e787962b0fbce92260f0b7020a322242342fc1af2d", 2167),
    "population_audit": ("7dd3eea3133dbed779071fd14e22df06ff5a0ddce994e4446cf4c6ef7b9cbe5a", 858),
    "parity_panel_seal": ("f67eabda02b19a1f1c0219278b65a656011f728141d94e49c83e0170f339ca5b", 1864),
}
V06_POPULATION_OPERATION_RECEIPT_SHA256 = "3f1730d904e96f105dd64a987754b388a9bccffac824a9ef70c674bf712c4815"
V06_POPULATION_OPERATION_RECEIPT_BYTES = 2057
EXPERIMENT_ROOT = Path(__file__).resolve().parents[2]
V06_REFERENCE_AUTHORIZATION_PATH = (
    EXPERIMENT_ROOT / "audits" / "e4-0-auth-issuer-v02" / "online-parity-authorization-v01.json"
)
V06_POPULATION_OPERATION_RECEIPT_PATH = (
    EXPERIMENT_ROOT / "audits" / "e4-0-execution" / "population-stage-seal-operation-v01.json"
)


class AuthorizationError(RuntimeError):
    """Invalid or incomplete authorization material; no receipt was written."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AuthorizationError(f"cannot read JSON object {path}: {error}") from error
    if not isinstance(value, dict):
        raise AuthorizationError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb", buffering=0) as stream:
        while chunk := stream.read(8 << 20):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _canonical_path(value: Any, *, must_exist: bool) -> Path:
    if not isinstance(value, str) or not value:
        raise AuthorizationError("all paths must be nonempty strings")
    path = Path(value)
    if not path.is_absolute():
        raise AuthorizationError(f"path is not absolute: {value}")
    try:
        resolved = path.resolve(strict=must_exist)
    except OSError as error:
        raise AuthorizationError(f"path cannot be resolved: {value}: {error}") from error
    if os.path.normpath(str(resolved)) != str(resolved):
        raise AuthorizationError(f"path is not normalized: {value}")
    return resolved


def artifact_identity(path_value: str | Path) -> dict[str, Any]:
    path = _canonical_path(str(path_value), must_exist=True)
    if not path.is_file():
        raise AuthorizationError(f"bound artifact is not a regular file: {path}")
    digest, size = _sha256(path)
    return {"path": str(path), "sha256": digest, "bytes": size}


def _artifact_identities(raw: Any, stage: str) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict) or set(raw) != ARTIFACTS_BY_STAGE[stage]:
        missing = sorted(ARTIFACTS_BY_STAGE[stage] - set(raw) if isinstance(raw, dict) else ARTIFACTS_BY_STAGE[stage])
        extra = sorted(set(raw) - ARTIFACTS_BY_STAGE[stage]) if isinstance(raw, dict) else []
        raise AuthorizationError(f"artifact role set mismatch; missing={missing}, extra={extra}")
    result: dict[str, dict[str, Any]] = {}
    for role, path_value in raw.items():
        folded_role = role.casefold()
        path_text = str(path_value).replace("\\", "/").casefold()
        if "label" in folded_role or "escrow" in folded_role or "/labels/" in path_text or "terminal-label" in path_text or "escrow" in path_text:
            raise AuthorizationError(f"pre-scoring authorization cannot bind truth/escrow artifact: {role}")
        result[role] = artifact_identity(path_value)
    return result


def _contract_binding(artifacts: Mapping[str, Mapping[str, Any]]) -> tuple[str, str, str, dict[str, Any]]:
    contract_entry = artifacts["e4_contract"]
    manifest_entry = artifacts["e4_contract_seal_manifest"]
    audit_entry = artifacts["e4_contract_audit"]
    contract = _read_json(Path(contract_entry["path"]))
    seal = _read_json(Path(manifest_entry["path"]))
    audit = _read_json(Path(audit_entry["path"]))
    if contract.get("contract_id") != CONTRACT_ID or contract.get("status") != "SEALED":
        raise AuthorizationError("bound E4 contract is not the final sealed v16 contract")
    contract_hash = str(contract_entry["sha256"])
    seal_fields = {
        "schema", "status", "seal_id", "stage", "path_root_kind", "created_utc",
        "contract_sha256", "contract_seal_root_sha256", "exact_predecessor_roots",
        "entries", "entry_count", "root_sha256",
    }
    seal_bytes = Path(manifest_entry["path"]).read_bytes()
    try:
        canonical_seal_bytes = (json.dumps(seal, ensure_ascii=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError) as error:
        raise AuthorizationError("contract seal manifest is not canonical JSON data") from error
    if (
        set(seal) != seal_fields
        or seal_bytes != canonical_seal_bytes
        or not isinstance(seal.get("created_utc"), str)
        or seal.get("schema") != ARTIFACT_SEAL_SCHEMA
        or seal.get("status") != "SEALED"
        or seal.get("seal_id") != CONTRACT_SEAL_ID
        or seal.get("stage") != "E4_0_CONTRACT"
        or seal.get("path_root_kind") != "WORKSPACE_ROOT"
        or seal.get("contract_seal_root_sha256") is not None
        or seal.get("exact_predecessor_roots") != PREDECESSOR_ROOTS
    ):
        raise AuthorizationError("bound contract seal manifest identity or canonical schema is malformed")
    root = seal.get("root_sha256")
    if not isinstance(root, str) or HEX64.fullmatch(root) is None:
        raise AuthorizationError("contract seal root is malformed")
    if seal.get("contract_sha256") != contract_hash:
        raise AuthorizationError("contract seal manifest binds different contract bytes")
    entries = seal.get("entries")
    if not isinstance(entries, list) or seal.get("entry_count") != len(entries) or not entries:
        raise AuthorizationError("contract seal manifest entry inventory is malformed")
    artifact_ids: set[str] = set()
    member_paths: set[str] = set()
    for row in entries:
        if (
            not isinstance(row, dict)
            or set(row) != {"artifact_id", "path", "bytes", "sha256"}
            or not isinstance(row.get("artifact_id"), str)
            or not row["artifact_id"]
            or not isinstance(row.get("path"), str)
            or not row["path"]
            or type(row.get("bytes")) is not int
            or row["bytes"] < 0
            or not isinstance(row.get("sha256"), str)
            or HEX64.fullmatch(row["sha256"]) is None
        ):
            raise AuthorizationError("contract seal member identity is malformed")
        if row["artifact_id"] in artifact_ids or row["path"] in member_paths:
            raise AuthorizationError("contract seal contains duplicate member identity")
        artifact_ids.add(row["artifact_id"])
        member_paths.add(row["path"])
    root_builder = hashlib.sha256()
    for row in sorted(entries, key=lambda item: item["artifact_id"].encode("utf-8")):
        root_builder.update(
            f"{row['artifact_id']}\t{row['path']}\t{row['bytes']}\t{row['sha256']}\n".encode("utf-8")
        )
    if root_builder.hexdigest() != root:
        raise AuthorizationError("contract seal root does not match its member inventory")
    contract_members = [row for row in entries if row["artifact_id"] == CONTRACT_MEMBER_ARTIFACT_ID]
    matching_bytes = [row for row in entries if row["sha256"] == contract_hash and row["bytes"] == contract_entry["bytes"]]
    if len(contract_members) != 1 or len(matching_bytes) != 1 or contract_members[0] is not matching_bytes[0]:
        raise AuthorizationError("contract seal does not bind exactly one matching v16 contract member")
    contract_member = contract_members[0]
    if (
        contract_member["path"] != CONTRACT_MEMBER_PATH
        or contract_member["sha256"] != contract_hash
        or contract_member["bytes"] != contract_entry["bytes"]
    ):
        raise AuthorizationError("contract seal does not bind the exact final v16 contract path and bytes")
    final_seal = audit.get("final_seal")
    final_seal_root = final_seal.get("root_sha256") if isinstance(final_seal, dict) else None
    audit_root = audit.get("e4_0_contract_root_sha256", audit.get("contract_root_sha256", audit.get(
        "contract_seal_root_sha256", final_seal_root)))
    if audit_root != root or "PASS" not in str(audit.get("status", "")).upper():
        raise AuthorizationError("independent contract audit does not pass on the exact sealed root")
    _validate_v11_direct_supersession(contract)
    _validate_v15_preseal_lineage(contract)
    predecessors = contract.get("predecessors")
    if not isinstance(predecessors, dict) or any(
        predecessors.get(key) != value for key, value in PREDECESSOR_ROOTS.items()
    ):
        raise AuthorizationError("final E4 contract does not preserve the required E0/E1/E2/E3 predecessor roots")
    return contract_hash, str(manifest_entry["sha256"]), root, contract


def _validate_v11_direct_supersession(contract: Mapping[str, Any]) -> None:
    """Require v15 to name the exact sealed v11 contract and seal as last sealed ancestor."""
    expected = {
        "contract": {
            "contract_id": V11_CONTRACT_ID,
            "path": "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v11-final.json",
            "bytes": V11_CONTRACT_BYTES,
            "sha256": V11_CONTRACT_SHA256,
        },
        "seal": {
            "seal_id": V11_SEAL_ID,
            "path": "experiments/fas-frozen-observer-bundle-engineering-v01/seals/e4-0-contract-v11-seal.json",
            "manifest_bytes": V11_SEAL_BYTES,
            "manifest_sha256": V11_SEAL_SHA256,
            "root_sha256": V11_SEAL_ROOT,
            "contract_member_artifact_id": "E4_0_CONTRACT_V11_FINAL",
        },
    }
    if contract.get("supersedes") != expected:
        raise AuthorizationError("v16 contract does not directly supersede the exact sealed v11 contract and seal")


def _validate_v15_preseal_lineage(contract: Mapping[str, Any]) -> None:
    """Require exact v15 failed-preseal identity and flattened inherited lineage."""
    amendment = contract.get("engineering_amendment")
    if not isinstance(amendment, Mapping):
        raise AuthorizationError("v16 contract is missing its engineering amendment lineage")
    v14_path = EXPERIMENT_ROOT / "contracts" / "e4-0-contract-v14-final.json"
    v14_amendment = _read_json(v14_path).get("engineering_amendment")
    v15_path = EXPERIMENT_ROOT / "contracts" / "e4-0-contract-v15-final.json"
    v15_map_path = EXPERIMENT_ROOT / "plans" / "E4-0-IMPLEMENTATION-SOURCE-MAP-v15.md"
    v15_stop_path = EXPERIMENT_ROOT / "audits" / "e4-0-track-e" / "track-e-preseal-receipt-v15.json"
    for path, expected_sha, expected_bytes in (
        (v15_path, V15_CONTRACT_SHA256, V15_CONTRACT_BYTES),
        (v15_map_path, V15_MAP_SHA256, V15_MAP_BYTES),
        (v15_stop_path, V15_PRESEAL_SHA256, V15_PRESEAL_BYTES),
    ):
        if _sha256(path) != (expected_sha, expected_bytes):
            raise AuthorizationError(f"preserved v15 candidate identity changed: {path}")
    previous = _read_json(v15_path)
    stop = _read_json(v15_stop_path)
    absent_contact = ("authorization_written", "tokenizer_contact", "model_contact", "cuda_initialized",
                      "gpu_lease_acquired", "feature_cache_created", "labels_opened")
    if (previous.get("contract_id") != "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V15"
            or previous.get("status") != "SEALED"
            or stop.get("status") != V15_PRESEAL_STATUS or stop.get("issues") != V15_PRESEAL_ISSUES
            or stop.get("pass") is not False or stop.get("final_seal") is not None
            or any(stop.get(key) is not False for key in ("population_truth_files_opened", "template_or_joint_truth_opened"))
            or any(key in stop for key in absent_contact)):
        raise AuthorizationError("preserved v15 preseal receipt differs from the exact no-contact three-issue stop")
    if not isinstance(v14_amendment, Mapping):
        raise AuthorizationError("sealed v14 predecessor amendment is missing")
    expected = dict(v14_amendment)
    expected.update({
        "amendment_kind": V16_AMENDMENT_KIND,
        "immediate_predecessor": {
            "contract": {"contract_id": previous["contract_id"], "path": V15_CONTRACT_REL,
                         "bytes": V15_CONTRACT_BYTES, "sha256": V15_CONTRACT_SHA256},
            "source_map": {"path": V15_MAP_REL, "bytes": V15_MAP_BYTES, "sha256": V15_MAP_SHA256},
            "preseal_receipt": {"path": V15_PRESEAL_REL, "bytes": V15_PRESEAL_BYTES,
                                "sha256": V15_PRESEAL_SHA256, "status": V15_PRESEAL_STATUS},
        },
        "failed_v15_preseal_attempt": {
            "source_map": stop["source_map"], "contract": stop["contract"],
            "preseal_receipt": {"path": V15_PRESEAL_REL, "bytes": V15_PRESEAL_BYTES,
                                "sha256": V15_PRESEAL_SHA256, "status": V15_PRESEAL_STATUS},
            "issues": list(V15_PRESEAL_ISSUES), "pass": False, "final_seal": None,
            "population_truth_files_opened": False, "template_or_joint_truth_opened": False,
        },
        "scope": V16_SCOPE,
    })
    if dict(amendment) != expected:
        raise AuthorizationError("v16 amendment does not preserve flattened v12-v14 lineage and exact v15 stop")

def _seal_root(artifact: Mapping[str, Any], role: str, expected_stage: str | None = None) -> str:
    value = _read_json(Path(artifact[role]["path"]))
    if expected_stage is not None and value.get("stage") != expected_stage:
        raise AuthorizationError(f"{role} names stage {value.get('stage')!r}, expected {expected_stage!r}")
    if value.get("schema") != ARTIFACT_SEAL_SCHEMA or value.get("status") != "SEALED":
        raise AuthorizationError(f"{role} is not a sealed E4 artifact manifest")
    root = value.get("root_sha256")
    if not isinstance(root, str) or HEX64.fullmatch(root) is None:
        raise AuthorizationError(f"{role} root is malformed")
    return root


def _population_audit_truth_closed_pass(audit: Mapping[str, Any], population_root: str) -> bool:
    """Validate population audit semantics across legacy and sealed schemas.

    The support-read field was serialized at the top level by the legacy
    fixture and under ``primary_support`` by the actual independent auditor.
    If both are present they must agree and both must be literal ``False``.
    """
    if (
        audit.get("population_root_sha256") != population_root
        or audit.get("status") != "PASS_POPULATION_FRESHNESS_SUPPORT"
        or audit.get("all_checks_passed") is not True
        or audit.get("population_truth_files_opened") is not False
    ):
        return False
    top_present = "heldout_or_joint_support_read" in audit
    top_value = audit.get("heldout_or_joint_support_read")
    support = audit.get("primary_support")
    if support is not None:
        if not isinstance(support, Mapping) or "heldout_or_joint_support_read" not in support:
            return False
        nested_value = support.get("heldout_or_joint_support_read")
        if nested_value is not False or (top_present and top_value is not nested_value):
            return False
        if top_present and top_value is not False:
            return False
        return True
    return top_present and top_value is False


def _verify_v06_reference_authorization() -> dict[str, Any]:
    """Load the preserved v06 online authorization only as an identity index.

    Its pre-contact stop produced no parity result.  This function uses it to
    pin the already sealed population and parity-panel files, never to infer a
    result or to reopen any sealed member data.
    """
    reference_path = V06_REFERENCE_AUTHORIZATION_PATH
    digest, size = _sha256(reference_path)
    if digest != V06_REFERENCE_AUTHORIZATION_SHA256 or size != V06_REFERENCE_AUTHORIZATION_BYTES:
        raise AuthorizationError("preserved v06 authorization reference bytes changed")
    reference = _read_json(reference_path)
    if (
        reference.get("schema") != SCHEMA
        or reference.get("authorization_id") != AUTHORIZATION_ID
        or reference.get("status") != "AUTHORIZED"
        or reference.get("stage") != "ONLINE_CACHE_PARITY"
        or reference.get("contract_sha256") != V06_CONTRACT_SHA256
        or reference.get("contract_seal_manifest_sha256") != V06_CONTRACT_SEAL_MANIFEST_SHA256
        or reference.get("contract_seal_root_sha256") != V06_CONTRACT_SEAL_ROOT_SHA256
    ):
        raise AuthorizationError("preserved v06 authorization reference has unexpected contract/stage identity")
    roots = reference.get("exact_predecessor_roots")
    if not isinstance(roots, dict) or any(
        roots.get(key) != value for key, value in {**PREDECESSOR_ROOTS, **V06_INHERITED_ROOTS}.items()
    ):
        raise AuthorizationError("preserved v06 authorization does not carry the frozen population/panel roots")
    artifacts = reference.get("artifacts")
    if not isinstance(artifacts, dict):
        raise AuthorizationError("preserved v06 authorization has no artifact identity map")
    for role in ("e4_contract", "e4_contract_seal_manifest"):
        entry = artifacts.get(role)
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "bytes"}:
            raise AuthorizationError(f"preserved v06 authorization omits {role}")
        if (entry["sha256"], entry["bytes"]) != (
            V06_CONTRACT_SHA256 if role == "e4_contract" else V06_CONTRACT_SEAL_MANIFEST_SHA256,
            V06_CONTRACT_BYTES if role == "e4_contract" else V06_CONTRACT_SEAL_MANIFEST_BYTES,
        ):
            raise AuthorizationError(f"preserved v06 authorization changed the {role} identity")
        actual = artifact_identity(entry["path"])
        if actual != {"path": str(_canonical_path(entry["path"], must_exist=True)), "sha256": entry["sha256"], "bytes": entry["bytes"]}:
            raise AuthorizationError(f"preserved v06 {role} file no longer matches its authorization record")
    v06_contract = _read_json(Path(artifacts["e4_contract"]["path"]))
    v06_seal = _read_json(Path(artifacts["e4_contract_seal_manifest"]["path"]))
    if (
        v06_contract.get("contract_id") != V06_CONTRACT_ID
        or v06_contract.get("status") != "SEALED"
    ):
        raise AuthorizationError("preserved v06 contract identity changed")
    if (
        v06_seal.get("schema") != ARTIFACT_SEAL_SCHEMA
        or v06_seal.get("stage") != "E4_0_CONTRACT"
        or v06_seal.get("seal_id") != V06_CONTRACT_SEAL_ID
        or v06_seal.get("root_sha256") != V06_CONTRACT_SEAL_ROOT_SHA256
        or v06_seal.get("contract_sha256") != V06_CONTRACT_SHA256
        or not any(
            isinstance(row, dict) and row.get("sha256") == V06_CONTRACT_SHA256
            for row in v06_seal.get("entries", [])
        )
    ):
        raise AuthorizationError("preserved v06 contract seal identity changed")
    return reference


def _verify_v06_inherited_seals(stage: str, artifacts: Mapping[str, Mapping[str, Any]]) -> None:
    """Pin inherited v06 seals/receipt bytes and inspect only their metadata."""
    if stage == "POPULATION_GENERATION":
        return
    reference = _verify_v06_reference_authorization()
    reference_artifacts = reference["artifacts"]
    roles = ["population_seal", "population_audit"]
    has_panel = stage in {"ONLINE_CACHE_PARITY", "FRESH_FEATURE_EXTRACTION", "FRESH_SCORING"}
    if has_panel:
        roles.append("parity_panel_seal")
    for role in roles:
        expected = reference_artifacts.get(role)
        actual = artifacts.get(role)
        if not isinstance(expected, dict) or not isinstance(actual, Mapping):
            raise AuthorizationError(f"v08 stage lacks preserved v06 artifact {role}")
        if (actual.get("path"), actual.get("sha256"), actual.get("bytes")) != (
            expected.get("path"), expected.get("sha256"), expected.get("bytes"),
        ):
            raise AuthorizationError(f"v08 stage does not reuse the exact v06 {role} bytes and path")
        pinned_sha, pinned_bytes = V06_INHERITED_ARTIFACT_IDENTITIES[role]
        if (actual.get("sha256"), actual.get("bytes")) != (pinned_sha, pinned_bytes):
            raise AuthorizationError(f"v08 stage changed the sealed v06 {role} identity")

    population_root = _seal_root(artifacts, "population_seal", "POPULATION_GENERATION")
    if population_root != V06_INHERITED_ROOTS["e4_population_root_sha256"]:
        raise AuthorizationError("v08 stage does not inherit the exact v06 population seal root")
    population_audit = _read_json(Path(artifacts["population_audit"]["path"]))
    if not _population_audit_truth_closed_pass(population_audit, population_root):
        raise AuthorizationError("preserved population audit receipt is not the exact truth-closed pass")
    if artifacts["population_audit"]["sha256"] != V06_INHERITED_ROOTS["e4_population_audit_root_sha256"]:
        raise AuthorizationError("v08 stage does not inherit the exact v06 population audit receipt")

    operation_path = V06_POPULATION_OPERATION_RECEIPT_PATH
    operation_sha, operation_bytes = _sha256(operation_path)
    if operation_sha != V06_POPULATION_OPERATION_RECEIPT_SHA256 or operation_bytes != V06_POPULATION_OPERATION_RECEIPT_BYTES:
        raise AuthorizationError("preserved population seal-operation receipt bytes changed")
    operation = _read_json(operation_path)
    if (
        operation.get("status") != "POPULATION_STAGE_SEALED"
        or operation.get("stage_seal_root_sha256") != population_root
        or "by byte length and SHA-256 only" not in str(operation.get("truth_handling", ""))
    ):
        raise AuthorizationError("preserved population seal-operation receipt does not match the inherited seal")

    if has_panel:
        panel_root = _seal_root(artifacts, "parity_panel_seal", "PARITY_PANEL_MATERIALIZATION")
        if panel_root != V06_INHERITED_ROOTS["e4_parity_panel_root_sha256"]:
            raise AuthorizationError("v08 stage does not inherit the exact v06 parity-panel seal root")


def _verify_historical(artifacts: Mapping[str, Mapping[str, Any]]) -> None:
    for root_key, role in ROOT_FILE_ROLES.items():
        if root_key in PREDECESSOR_ROOTS:
            value = _read_json(Path(artifacts[role]["path"]))
            root = value.get("root_sha256", value.get("e3_root_sha256"))
            if root != PREDECESSOR_ROOTS[root_key]:
                raise AuthorizationError(f"{role} does not match frozen historical root {root_key}")
    audit_expectations = {
        "e0_audit": ("seal_root_sha256", PREDECESSOR_ROOTS["e0_v10_root_sha256"]),
        "e1_audit": ("e1_root_sha256", PREDECESSOR_ROOTS["e1_v04_root_sha256"]),
        "e2_audit": ("e2_root_sha256", PREDECESSOR_ROOTS["e2_v07_root_sha256"]),
        "e3_audit": ("e3_root_sha256", PREDECESSOR_ROOTS["e3_v02_bundle_root_sha256"]),
    }
    for role, (root_key, expected) in audit_expectations.items():
        audit = _read_json(Path(artifacts[role]["path"]))
        if "PASS" not in str(audit.get("status", "")).upper() or audit.get(root_key) != expected:
            raise AuthorizationError(f"{role} is not a passing audit for its exact historical root")


def _predecessor_roots(stage: str, artifacts: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    _verify_historical(artifacts)
    roots = dict(PREDECESSOR_ROOTS)
    if stage == "POPULATION_GENERATION":
        return roots
    population_root = _seal_root(artifacts, "population_seal", "POPULATION_GENERATION")
    population_audit = _read_json(Path(artifacts["population_audit"]["path"]))
    if not _population_audit_truth_closed_pass(population_audit, population_root):
        raise AuthorizationError("population audit does not independently pass the bound population seal")
    roots["e4_population_root_sha256"] = population_root
    roots["e4_population_audit_root_sha256"] = artifacts["population_audit"]["sha256"]
    panel_root = _seal_root(artifacts, "parity_panel_seal", "PARITY_PANEL_MATERIALIZATION")
    roots["e4_parity_panel_root_sha256"] = panel_root
    if stage == "ONLINE_CACHE_PARITY":
        return roots
    parity_root = _seal_root(artifacts, "parity_receipt_seal", "ONLINE_CACHE_PARITY")
    parity_seal = _read_json(Path(artifacts["parity_receipt_seal"]["path"]))
    parity_entries = parity_seal.get("entries", [])
    receipt_entry = next((row for row in parity_entries if isinstance(row, dict) and row.get("artifact_id") == "parity_receipt"), None)
    if receipt_entry is None:
        raise AuthorizationError("online/cache parity seal does not bind the expected parity_receipt member")
    receipt_path = Path(artifacts["parity_receipt_seal"]["path"]).parent.parent / receipt_entry["path"]
    parity_receipt = _read_json(receipt_path)
    if parity_receipt.get("status") != "ONLINE_CACHE_PARITY_PASS":
        raise AuthorizationError("online/cache parity receipt is not passing")
    roots["e4_parity_receipt_root_sha256"] = parity_root
    if stage == "FRESH_FEATURE_EXTRACTION":
        return roots
    feature_root = _seal_root(artifacts, "feature_cache_seal", "FRESH_FEATURE_EXTRACTION")
    feature_seal = _read_json(Path(artifacts["feature_cache_seal"]["path"]))
    feature_entry = next((row for row in feature_seal.get("entries", []) if isinstance(row, dict) and row.get("artifact_id") == "feature_extraction_receipt"), None)
    if feature_entry is None:
        raise AuthorizationError("fresh feature seal does not bind the expected extraction receipt member")
    feature_path = Path(artifacts["feature_cache_seal"]["path"]).parent.parent / feature_entry["path"]
    feature_receipt = _read_json(feature_path)
    if feature_receipt.get("status") != "FEATURE_CACHE_COMPLETE_GATE_PASS":
        raise AuthorizationError("fresh feature extraction receipt is not passing")
    roots["e4_feature_cache_root_sha256"] = feature_root
    return roots


def _paths(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict) or set(raw) != PATH_KEYS:
        raise AuthorizationError(f"paths must contain exactly: {sorted(PATH_KEYS)}")
    return {key: str(_canonical_path(value, must_exist=True)) for key, value in raw.items()}


def _gpu_lease(raw: Any, stage: str) -> tuple[dict[str, Any], bool]:
    if not isinstance(raw, dict) or set(raw) != {"lock_path"}:
        raise AuthorizationError("gpu_lease input must contain only lock_path")
    lock_path = _canonical_path(raw["lock_path"], must_exist=False)
    lease = {
        "lock_path": str(lock_path),
        "expected_reserved_ceiling_bytes": GPU_RESERVED_LIMIT_BYTES,
        "quiet_window_seconds": GPU_QUIET_WINDOW_SECONDS,
        "poll_interval_seconds": GPU_POLL_INTERVAL_SECONDS,
    }
    required = stage in {"ONLINE_CACHE_PARITY", "FRESH_FEATURE_EXTRACTION"}
    return lease, required


def build_authorization(
    *,
    stage: str,
    bindings: Mapping[str, Any],
    now_unix_seconds: int | None = None,
) -> dict[str, Any]:
    """Build and validate an auth object without writing it or touching ML runtimes."""
    if stage not in ARTIFACTS_BY_STAGE:
        raise AuthorizationError(f"unsupported E4 stage: {stage}")
    duration = bindings.get("valid_for_seconds", DEFAULT_VALIDITY_SECONDS)
    if type(duration) is not int or not 1 <= duration <= MAX_VALIDITY_SECONDS:
        raise AuthorizationError(f"valid_for_seconds must be an integer in [1,{MAX_VALIDITY_SECONDS}]")
    output_root = _canonical_path(bindings.get("output_root"), must_exist=False)
    artifacts = _artifact_identities(bindings.get("artifacts"), stage)
    contract_sha, seal_manifest_sha, contract_root, _contract = _contract_binding(artifacts)
    _verify_historical(artifacts)
    _verify_v06_inherited_seals(stage, artifacts)
    roots = _predecessor_roots(stage, artifacts)
    expected_count = 4 + len(roots) - len(PREDECESSOR_ROOTS)
    expected_roles = set(ROOT_ORDER[:expected_count])
    if set(roots) != expected_roles:
        raise AuthorizationError("derived predecessor-root set differs from the normative stage prefix")
    for key, value in roots.items():
        if not isinstance(value, str) or HEX64.fullmatch(value) is None:
            raise AuthorizationError(f"derived predecessor root is malformed: {key}")
    issued = int(time.time()) if now_unix_seconds is None else now_unix_seconds
    if isinstance(issued, bool) or not isinstance(issued, int) or issued < 0:
        raise AuthorizationError("issued time must be a finite nonnegative Unix integer")
    true_scope = TRUE_SCOPES[stage]
    auth: dict[str, Any] = {
        "schema": SCHEMA,
        "authorization_id": AUTHORIZATION_ID,
        "status": "AUTHORIZED",
        "stage": stage,
        "contract_sha256": contract_sha,
        "contract_seal_manifest_sha256": seal_manifest_sha,
        "contract_seal_root_sha256": contract_root,
        "exact_predecessor_roots": roots,
        "output_root": str(output_root),
        "scope": {key: key in true_scope for key in SCOPE_KEYS},
        "authorized_by": "ACTIVE_USER_REQUEST",
        "issued_utc_unix_seconds": issued,
        "valid_from_utc_unix_seconds": issued,
        "valid_until_utc_unix_seconds": issued + duration,
    }
    if stage != "FRESH_SCORING":
        auth["artifacts"] = artifacts
        paths = _paths(bindings.get("paths"))
        for path_key, artifact_key in (
            ("model_asset_manifest", "model_manifest"),
            ("tokenizer_asset_manifest", "tokenizer_manifest"),
        ):
            if paths[path_key] != artifacts[artifact_key]["path"]:
                raise AuthorizationError(f"paths.{path_key} differs from its artifact-map identity")
        auth["paths"] = paths
        lease, required = _gpu_lease(bindings.get("gpu_lease"), stage)
        auth["gpu_lease"] = lease
        auth["gpu_lease_required_before_model_contact"] = required
    expected_keys = {
        "schema", "authorization_id", "status", "stage", "contract_sha256",
        "contract_seal_manifest_sha256", "contract_seal_root_sha256", "exact_predecessor_roots",
        "output_root", "scope", "authorized_by", "issued_utc_unix_seconds",
        "valid_from_utc_unix_seconds", "valid_until_utc_unix_seconds",
    }
    if stage != "FRESH_SCORING":
        expected_keys |= {"artifacts", "paths", "gpu_lease", "gpu_lease_required_before_model_contact"}
    if set(auth) != expected_keys:
        raise AuthorizationError("internal stage authorization field set mismatch")
    return auth


def create_once(path: Path, authorization: Mapping[str, Any]) -> tuple[int, str]:
    """Durably create one receipt and refuse replacement of an earlier attempt."""
    if not path.parent.is_dir():
        raise AuthorizationError(f"authorization output directory must already exist: {path.parent}")
    payload = (json.dumps(dict(authorization), ensure_ascii=True, indent=2) + "\n").encode("utf-8")
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise AuthorizationError(f"authorization receipt already exists; preserving it: {path}") from error
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        # Preserve a partial create-once attempt rather than silently replacing it.
        raise
    return len(payload), hashlib.sha256(payload).hexdigest()


def _load_bindings(path: Path) -> dict[str, Any]:
    value = _read_json(path.resolve(strict=True))
    expected = {"output_root", "artifacts", "paths", "gpu_lease", "valid_for_seconds"}
    if set(value) != expected:
        raise AuthorizationError(f"bindings file must contain exactly: {sorted(expected)}")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create one model-free, stage-scoped E4-0 authorization receipt.")
    parser.add_argument("--stage", choices=tuple(ARTIFACTS_BY_STAGE), required=True)
    parser.add_argument("--bindings", type=Path, required=True, help="JSON map of exact paths and stage artifacts")
    parser.add_argument("--output", type=Path, required=True, help="new receipt path; existing files are never replaced")
    args = parser.parse_args(argv)
    try:
        bindings = _load_bindings(args.bindings)
        authorization = build_authorization(stage=args.stage, bindings=bindings)
        count, digest = create_once(args.output, authorization)
    except Exception as error:
        print(f"E4-0 authorization stopped: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"status": "AUTHORIZED", "stage": args.stage, "path": str(args.output.resolve()), "bytes": count, "sha256": digest}, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



