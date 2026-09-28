"""Strict input binding for the Ledger-supervised E4-0 runner.

This module carries no stage authority and acquires no lease. The parent
KAMMI_LOCAL_EXECUTION_V1 worker owns authorization, fencing, process lifetime,
output import, and the external completion receipt.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


ADAPTER_ID = "FAS_FROZEN_OBSERVER_BUNDLE_E4_0_LEDGER_SUPERVISED_ADAPTER_V02"
SCHEMA = "FAS_E4_0_SUPERVISED_EXECUTION_BINDING_V02"
CONTRACT_SHA256 = "21fc77d5a288b9adef995d88f089890235f8dcb2fbc3c9e452725bb67892a22f"
CONTRACT_ROOT = "278ae16eeb6852d3efad44221556a87be6df54964471f0870931fe2e99b305d1"
CONTRACT_ID = "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V16"
CONTRACT_SEAL_ID = "FAS_E4_0_CONTRACT_V16_V09_SEAL"
CONTRACT_MEMBER_ID = "E4_0_CONTRACT_V16_V09_FINAL"
CONTRACT_MEMBER_PATH = "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v16-v09-final.json"
CONTRACT_SEAL_MANIFEST_SHA256 = "0635de4a384b4d5121d8b2295e88a73f649c53e402ffcda311fcaf9c8d93099c"
CONTRACT_SEAL_MANIFEST_BYTES = 171_220
CONTRACT_AUDIT_SHA256 = "8b05f33e615c1484690890ffd8933b31a1fe6e21f61831266ff3b278cec32b64"
CONTRACT_AUDIT_BYTES = 165_290
CONTRACT_AUDIT_STATUS = "E4_0_TRACK_E_POSTSEAL_PASS_V16_V11_SEAL_ROOT_AND_MEMBERS_RECOMPUTED"
CONTRACT_AUDIT_RECEIPT_ID = "FAS_E4_0_TRACK_E_V16_V11_POSTSEAL_AUDIT_V01"
CONTRACT_PREDECESSOR_ROOTS = {
    "e0_v10_root_sha256": "899a131c09298fdafdcc6771ad01e8982857a1cd47900259800f97dd7bea7ccd",
    "e1_v04_root_sha256": "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03",
    "e2_v07_root_sha256": "a2e2aa76f77904665b9abfa2a22f609c05219d8bc64c537bed41f5c634d1da8a",
    "e3_v02_bundle_root_sha256": "899ff6a61272b86fdf1cd51d8c14100e77185157c242f27fbffe452803a435e1",
}
LIBRARY_ACCEPTANCE_ID = "sha256:f98dcd6743c5e8b7ff091cef2d69aa361e53c252711c7b001f3a71d322744602"
HANDOFF_SEAL_ROOT = "ad1ffbc9203fd0cac5553ea4a5d3c72654c22054e68348474414096e35dd8cc5"
VISIBLE_BRIDGE_ROOT = "aacfd286b6349f0b35adb853a2cd9717c2463fedfeccc052bafaf515c69b027b"

COMMON_ARTIFACTS = frozenset({
    "e4_contract", "e4_contract_seal_manifest", "e4_contract_audit",
    "e1_audit", "e2_audit", "e3_audit", "population_seal", "population_audit",
    "population_inputs", "population_rows", "parity_inputs", "parity_rows",
    "parity_selection_receipt",
})
MODE_ARTIFACTS = {
    "parity": frozenset({
        "representation_abi", "model_manifest", "tokenizer_manifest",
        "e2_cache", "e3_bundle", "parity_panel_seal",
    }),
    "extract-e4": frozenset({
        "representation_abi", "model_manifest", "tokenizer_manifest",
        "parity_panel_seal", "parity_receipt_seal", "parity_receipt",
        "online_feature_cache",
    }),
}
MODE_STAGE = {
    "parity": "ONLINE_CACHE_PARITY",
    "extract-e4": "FRESH_FEATURE_EXTRACTION",
}
OUTPUTS = {
    "parity": (
        "parity-online-features.f32le",
        "parity-receipt-v01.json",
        "stage-seal-v01.json",
    ),
    "extract-e4": (
        "V1_FINAL_POSITION.f32le",
        "feature-extraction-receipt-v01.json",
        "population-row-manifest-v01.jsonl",
        "stage-seal-v01.json",
    ),
}
MODE_OUTPUT_DIR = {"parity": "parity", "extract-e4": "features"}
PATH_KEYS = frozenset({
    "model_snapshot", "tokenizer_snapshot",
    "model_asset_manifest", "tokenizer_asset_manifest",
})
BASE_PREDECESSOR_ROOT_KEYS = frozenset({
    "e0_v10_root_sha256", "e1_v04_root_sha256", "e2_v07_root_sha256",
    "e3_v02_bundle_root_sha256", "e4_population_root_sha256",
    "e4_population_audit_root_sha256", "e4_parity_panel_root_sha256",
})
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class BindingError(ValueError):
    """The static Fabrique input binding is malformed or out of scope."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BindingError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _require_sha256(value: Any, name: str) -> None:
    if not isinstance(value, str) or HEX64.fullmatch(value) is None:
        raise BindingError(f"{name} must be lowercase SHA-256 hex")


def _read_bound_json(entry: Any, name: str, expected_sha256: str, expected_bytes: int) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "bytes"}:
        raise BindingError(f"current E4 contract binding is incomplete: {name}")
    if entry["sha256"] != expected_sha256 or entry["bytes"] != expected_bytes:
        raise BindingError(f"current E4 contract binding identity differs: {name}")
    path_value = entry["path"]
    if not isinstance(path_value, str) or not Path(path_value).is_absolute():
        raise BindingError(f"current E4 contract artifact path must be absolute: {name}")
    path = Path(path_value).resolve(strict=True)
    raw = path.read_bytes()
    if len(raw) != expected_bytes or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise BindingError(f"current E4 contract artifact bytes differ: {name}")
    try:
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BindingError(f"current E4 contract artifact is invalid JSON: {name}") from error
    if not isinstance(value, dict):
        raise BindingError(f"current E4 contract artifact must be a JSON object: {name}")
    return value, {"path": str(path), "sha256": expected_sha256, "bytes": expected_bytes}


def verify_current_contract_binding(authorization: dict[str, Any]) -> dict[str, Any]:
    """Verify the actual sealed E4-0 v16 contract lineage without legacy v09 logic."""
    if authorization.get("contract_sha256") != CONTRACT_SHA256:
        raise BindingError("execution binding does not identify the sealed E4-0 v16 contract bytes")
    if authorization.get("contract_seal_manifest_sha256") != CONTRACT_SEAL_MANIFEST_SHA256:
        raise BindingError("execution binding does not identify the sealed E4-0 v16-v09 manifest bytes")
    if authorization.get("contract_seal_root_sha256") != CONTRACT_ROOT:
        raise BindingError("execution binding does not identify the sealed E4-0 v16-v09 root")
    artifacts = authorization.get("artifacts")
    if not isinstance(artifacts, dict):
        raise BindingError("execution binding has no current E4 contract artifacts")

    contract, contract_identity = _read_bound_json(
        artifacts.get("e4_contract"), "e4_contract", CONTRACT_SHA256, 146_087,
    )
    seal, seal_identity = _read_bound_json(
        artifacts.get("e4_contract_seal_manifest"), "e4_contract_seal_manifest",
        CONTRACT_SEAL_MANIFEST_SHA256, CONTRACT_SEAL_MANIFEST_BYTES,
    )
    audit, audit_identity = _read_bound_json(
        artifacts.get("e4_contract_audit"), "e4_contract_audit",
        CONTRACT_AUDIT_SHA256, CONTRACT_AUDIT_BYTES,
    )

    if contract.get("contract_id") != CONTRACT_ID or contract.get("status") != "SEALED":
        raise BindingError("current E4 contract identity/status is not the sealed v16 contract")
    frozen_authorization = contract.get("authorization")
    if not isinstance(frozen_authorization, dict) or any(
        frozen_authorization.get(key) is not False
        for key in (
            "population_generation_authorized", "tokenizer_contact_authorized",
            "model_contact_authorized", "feature_extraction_authorized",
            "evaluation_label_opening_authorized", "scoring_authorized",
            "fitting_authorized", "E4_A_authorized",
        )
    ):
        raise BindingError("sealed E4 contract authorization fields differ from the closed baseline")

    if (
        seal.get("schema") != "FAS_E4_0_ARTIFACT_SEAL_V01"
        or seal.get("status") != "SEALED"
        or seal.get("seal_id") != CONTRACT_SEAL_ID
        or seal.get("stage") != "E4_0_CONTRACT"
        or seal.get("path_root_kind") != "WORKSPACE_ROOT"
        or seal.get("contract_sha256") != CONTRACT_SHA256
        or seal.get("contract_seal_root_sha256") is not None
        or seal.get("root_sha256") != CONTRACT_ROOT
    ):
        raise BindingError("current E4 contract seal metadata differs from its sealed identity")
    entries = seal.get("entries")
    if not isinstance(entries, list) or len(entries) != 447 or seal.get("entry_count") != len(entries):
        raise BindingError("current E4 contract seal member count is invalid")
    if entries != sorted(entries, key=lambda item: str(item.get("artifact_id", "")).encode("utf-8")):
        raise BindingError("current E4 contract seal members are not canonically ordered")
    root_builder = hashlib.sha256()
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for member in entries:
        if not isinstance(member, dict) or set(member) != {"artifact_id", "path", "bytes", "sha256"}:
            raise BindingError("current E4 contract seal member schema is invalid")
        artifact_id, relative = member["artifact_id"], member["path"]
        if (
            not isinstance(artifact_id, str) or not artifact_id or artifact_id in seen_ids
            or not isinstance(relative, str) or relative.startswith("/") or "\\" in relative
            or any(part in ("", ".", "..") for part in relative.split("/"))
            or relative in seen_paths or type(member["bytes"]) is not int or member["bytes"] < 0
        ):
            raise BindingError("current E4 contract seal member identity is malformed or duplicated")
        _require_sha256(member["sha256"], f"seal member {artifact_id}.sha256")
        seen_ids.add(artifact_id)
        seen_paths.add(relative)
        root_builder.update(
            f"{artifact_id}\t{relative}\t{member['bytes']}\t{member['sha256']}\n".encode("utf-8")
        )
    if root_builder.hexdigest() != CONTRACT_ROOT:
        raise BindingError("current E4 contract seal root failed independent recomputation")
    contract_members = [member for member in entries if member["artifact_id"] == CONTRACT_MEMBER_ID]
    if len(contract_members) != 1 or contract_members[0] != {
        "artifact_id": CONTRACT_MEMBER_ID,
        "path": CONTRACT_MEMBER_PATH,
        "bytes": 146_087,
        "sha256": CONTRACT_SHA256,
    }:
        raise BindingError("current E4 contract seal does not contain the exact bound contract bytes")

    seal_predecessors = seal.get("exact_predecessor_roots")
    contract_predecessors = contract.get("predecessors")
    if not isinstance(seal_predecessors, dict) or not isinstance(contract_predecessors, dict):
        raise BindingError("current E4 contract predecessor roots are absent")
    if seal_predecessors != CONTRACT_PREDECESSOR_ROOTS or any(
        contract_predecessors.get(key) != value for key, value in CONTRACT_PREDECESSOR_ROOTS.items()
    ):
        raise BindingError("current E4 contract and seal predecessor roots differ from frozen inputs")
    bound_roots = authorization.get("exact_predecessor_roots")
    if not isinstance(bound_roots, dict) or any(
        bound_roots.get(key) != value for key, value in CONTRACT_PREDECESSOR_ROOTS.items()
    ):
        raise BindingError("execution binding predecessor roots differ from the sealed E4 contract")

    final_seal = audit.get("final_seal")
    if not isinstance(final_seal, dict):
        raise BindingError("independent E4 contract postseal audit omits its final seal identity")
    if (
        audit.get("receipt_id") != CONTRACT_AUDIT_RECEIPT_ID
        or audit.get("mode") != "POSTSEAL"
        or audit.get("pass") is not True
        or audit.get("status") != CONTRACT_AUDIT_STATUS
        or audit.get("issues") != []
        or audit.get("contract") != {
            "bytes": 146_087,
            "path": CONTRACT_MEMBER_PATH,
            "sha256": CONTRACT_SHA256,
        }
        or final_seal.get("path") != "experiments/fas-frozen-observer-bundle-engineering-v01/seals/e4-0-contract-v16-v09-seal.json"
        or final_seal.get("bytes") != CONTRACT_SEAL_MANIFEST_BYTES
        or final_seal.get("sha256") != CONTRACT_SEAL_MANIFEST_SHA256
        or final_seal.get("root_sha256") != CONTRACT_ROOT
        or final_seal.get("recomputed_root_sha256") != CONTRACT_ROOT
        or final_seal.get("root_match") is not True
        or final_seal.get("member_set_exact") is not True
        or final_seal.get("entry_count") != 447
        or final_seal.get("expected_member_count") != 447
        or audit.get("population_truth_files_opened") is not False
        or audit.get("template_or_joint_truth_opened") is not False
    ):
        raise BindingError("independent E4 contract postseal audit is not the exact passing v16-v11 receipt")

    return {
        "contract": contract,
        "seal": seal,
        "audit": audit,
        "root_sha256": CONTRACT_ROOT,
        "e4_contract": contract_identity,
        "e4_contract_seal_manifest": seal_identity,
        "e4_contract_audit": audit_identity,
    }


def validate_binding_document(value: Any, mode: str) -> dict[str, Any]:
    """Validate the non-authoritative E4 input map before scientific imports."""
    if mode not in MODE_ARTIFACTS:
        raise BindingError(f"unsupported E4 supervised mode: {mode}")
    if not isinstance(value, dict):
        raise BindingError("execution binding must be a JSON object")
    expected_fields = {
        "schema", "adapter_id", "mode", "stage", "contract_sha256",
        "contract_seal_manifest_sha256", "contract_seal_root_sha256",
        "output_root", "supervised_output_root", "inherited_stage_root",
        "expected_outputs", "exact_predecessor_roots",
        "artifacts", "paths", "library_handoff",
    }
    if set(value) != expected_fields:
        raise BindingError("execution binding fields differ from the frozen v1 schema")
    if value["schema"] != SCHEMA or value["adapter_id"] != ADAPTER_ID:
        raise BindingError("execution binding schema or adapter identity mismatch")
    if value["mode"] != mode or value["stage"] != MODE_STAGE[mode]:
        raise BindingError("execution binding is bound to another mode/stage")
    if value["contract_sha256"] != CONTRACT_SHA256:
        raise BindingError("execution binding does not identify E4-0 v16-v09 contract bytes")
    if value["contract_seal_root_sha256"] != CONTRACT_ROOT:
        raise BindingError("execution binding does not identify the sealed E4-0 v16-v09 root")
    _require_sha256(value["contract_seal_manifest_sha256"], "contract seal manifest hash")
    if not isinstance(value["output_root"], str) or not Path(value["output_root"]).is_absolute():
        raise BindingError("output_root must be an absolute path")
    if not isinstance(value["inherited_stage_root"], str) or not Path(value["inherited_stage_root"]).is_absolute():
        raise BindingError("inherited_stage_root must be an absolute path")
    expected_worker_root = Path(value["output_root"]).resolve() / MODE_OUTPUT_DIR[mode]
    if (not isinstance(value["supervised_output_root"], str)
            or Path(value["supervised_output_root"]).resolve() != expected_worker_root):
        raise BindingError("Ledger worker output_root must be the fresh mode-specific child of output_root")
    if value["expected_outputs"] != list(OUTPUTS[mode]):
        raise BindingError("output inventory differs from the fixed supervised E4 inventory")
    roots = value["exact_predecessor_roots"]
    expected_root_keys = BASE_PREDECESSOR_ROOT_KEYS | (
        {"e4_parity_receipt_root_sha256"} if mode == "extract-e4" else set()
    )
    if not isinstance(roots, dict) or set(roots) != expected_root_keys:
        raise BindingError("exact predecessor root set differs from the E4-0 contract")
    for key, digest in roots.items():
        _require_sha256(digest, key)
    required_artifacts = COMMON_ARTIFACTS | MODE_ARTIFACTS[mode]
    artifacts = value["artifacts"]
    if not isinstance(artifacts, dict) or set(artifacts) != required_artifacts:
        raise BindingError("artifact inventory differs from the fixed mode input inventory")
    for name, entry in artifacts.items():
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "bytes"}:
            raise BindingError(f"artifact identity is malformed: {name}")
        if not isinstance(entry["path"], str) or not Path(entry["path"]).is_absolute():
            raise BindingError(f"artifact path is not absolute: {name}")
        _require_sha256(entry["sha256"], f"{name}.sha256")
        if type(entry["bytes"]) is not int or entry["bytes"] < 0:
            raise BindingError(f"artifact byte length is invalid: {name}")
    paths = value["paths"]
    if not isinstance(paths, dict) or set(paths) != PATH_KEYS:
        raise BindingError("local model/tokenizer path inventory differs from v1")
    if any(not isinstance(path, str) or not Path(path).is_absolute() for path in paths.values()):
        raise BindingError("model/tokenizer asset paths must be absolute")
    handoff = value["library_handoff"]
    if not isinstance(handoff, dict) or set(handoff) != {
        "library_acceptance_id", "handoff_seal_root_sha256",
        "visible_inheritance_bridge_root_sha256",
    }:
        raise BindingError("Library handoff identity fields differ from the qualified handoff")
    if handoff != {
        "library_acceptance_id": LIBRARY_ACCEPTANCE_ID,
        "handoff_seal_root_sha256": HANDOFF_SEAL_ROOT,
        "visible_inheritance_bridge_root_sha256": VISIBLE_BRIDGE_ROOT,
    }:
        raise BindingError("Library handoff or visible-only bridge identity mismatch")

    # Reject authority-shaped fields anywhere in the static input object. Actual
    # run/stage grants, authorization, lease, and fence are handled by the parent
    # Ledger worker and are deliberately absent from this child binding.
    forbidden = {"authorization_id", "authorized_by", "status", "scope", "gpu_lease",
                 "lease_id", "resource_id", "fencing_token", "actor_token", "grant_id"}
    if forbidden.intersection(value):
        raise BindingError("static input binding must not carry authority or lease fields")
    return value


def load_binding(path: Path, mode: str) -> tuple[dict[str, Any], str]:
    resolved = path.resolve(strict=True)
    raw = resolved.read_bytes()
    value = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    binding = validate_binding_document(value, mode)
    return binding, hashlib.sha256(raw).hexdigest()
