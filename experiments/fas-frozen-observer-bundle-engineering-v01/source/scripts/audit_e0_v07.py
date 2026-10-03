from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT_REL = "experiments/fas-frozen-observer-bundle-engineering-v01"
PROJECT = REPO_ROOT / PROJECT_REL
E0_V06_ROOT = "968e7da8d44e36e31de81e87bdf140e7d766100891cecb7bbf9b4be80e99b3ea"
E1_V04_ROOT = "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03"
E2_V01_ROOT = "0ff309d833cd87017f7384247e4420a508f582ad9f375c5637f586d73b703f4c"
REFERENCE_SHA256 = "8eb80df5f73e761fe6c025fc1c66abef2027d639b6c14f56d4177d6e6a7a45a4"
REFERENCE_BYTES = 872_415_232
STATUS = "E0_FROZEN_NOT_AUTHORIZED_FOR_MODEL_CONTACT"
SEAL_PATH = PROJECT / "seals" / "e0-seal-v07.json"
RECEIPT_PATH = PROJECT / "audits" / "e0-v07-independent-audit-v01.json"


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb", buffering=0) as stream:
        while chunk := stream.read(8 << 20):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def tree_root(entries: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda row: row["path"]):
        digest.update(f'{entry["path"]}\t{entry["bytes"]}\t{entry["sha256"]}\n'.encode("utf-8"))
    return digest.hexdigest()


def verify_seal(path: Path, expected_root: str | None = None) -> dict[str, Any]:
    seal = read_json(path)
    actual = []
    for entry in seal.get("entries", []):
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"unsafe sealed path in {path.name}: {entry['path']}")
        digest, size = sha256_file(REPO_ROOT / relative)
        if digest != entry.get("sha256") or size != entry.get("bytes"):
            raise RuntimeError(f"sealed member mismatch: {entry['path']}")
        actual.append({"path": relative.as_posix(), "bytes": size, "sha256": digest})
    root = tree_root(actual)
    if root != seal.get("root_sha256") or len(actual) != seal.get("entry_count"):
        raise RuntimeError(f"seal root or count failed: {path.name}")
    if expected_root is not None and root != expected_root:
        raise RuntimeError(f"unexpected root for {path.name}: {root}")
    return seal


def member(seal: dict[str, Any], field: str) -> tuple[Path, str]:
    relative = seal.get(field)
    if not isinstance(relative, str):
        raise RuntimeError(f"seal lacks member reference {field}")
    normalized = Path(relative).as_posix()
    row = next((item for item in seal["entries"] if item.get("path") == normalized), None)
    if row is None:
        raise RuntimeError(f"seal reference is not a member: {field}")
    path = REPO_ROOT / Path(relative)
    digest, size = sha256_file(path)
    if digest != row["sha256"] or size != row["bytes"]:
        raise RuntimeError(f"referenced contract member mismatch: {field}")
    return path, digest


def require(checks: dict[str, bool], name: str, condition: bool) -> None:
    checks[name] = bool(condition)
    if not condition:
        raise RuntimeError(f"independent E0 v07 audit failed: {name}")


def main() -> int:
    predecessor_path = PROJECT / "seals" / "e0-seal-v06.json"
    predecessor = verify_seal(predecessor_path, E0_V06_ROOT)
    seal = verify_seal(SEAL_PATH)
    checks: dict[str, bool] = {}
    require(checks, "e0_v07_status_preserves_closed_authority", seal.get("status") == STATUS and seal.get("model_contact_authorized") is False)
    require(checks, "no_top_level_freeze_id_required", "freeze_id" not in seal)
    require(checks, "e1_and_e2_v01_predecessors_bound", seal.get("e1_v04_root_sha256") == E1_V04_ROOT and seal.get("e2_v01_preservation_root_sha256") == E2_V01_ROOT)
    require(checks, "predecessor_root_bound", seal.get("predecessor_e0_root_sha256") == E0_V06_ROOT)

    old_members = {row["path"]: row for row in predecessor["entries"]}
    new_members = {row["path"]: row for row in seal["entries"]}
    require(checks, "all_e0_v06_members_carried_forward_byte_exact", all(new_members.get(path) == row for path, row in old_members.items()))
    require(checks, "e0_v06_manifest_member_present", f"{PROJECT_REL}/seals/e0-seal-v06.json" in new_members)
    required_paths = {
        f"{PROJECT_REL}/contracts/e0-freeze-v07-sealed-v01.json",
        f"{PROJECT_REL}/contracts/e2-run-v04.json",
        f"{PROJECT_REL}/contracts/representation-abi-v04.json",
        f"{PROJECT_REL}/source/scripts/extract_features_v04.py",
        f"{PROJECT_REL}/source/scripts/e2_execution_identity_v04.py",
        f"{PROJECT_REL}/source/tests/test_e2_execution_identity_v04.py",
        f"{PROJECT_REL}/audits/e2-v02-authorized-attempt-stop-v01.json",
        f"{PROJECT_REL}/audits/e2-v03-authorized-attempt-stop-v01.json",
        f"{PROJECT_REL}/audits/e2-v03-model-contact-authorization-v01.json",
        f"{PROJECT_REL}/audits/e2-v02-concurrent-wait-complete-v01.json",
    }
    require(checks, "required_new_contract_source_and_history_members_present", required_paths <= new_members.keys())

    freeze_path, freeze_hash = member(seal, "freeze_contract_path")
    protocol_path, protocol_hash = member(seal, "e2_protocol_path")
    abi_path, abi_hash = member(seal, "representation_abi_path")
    freeze = read_json(freeze_path)
    protocol = read_json(protocol_path)
    abi = read_json(abi_path)
    old_freeze = read_json(PROJECT / "contracts" / "e0-freeze-v06-sealed-v03.json")
    old_protocol = read_json(PROJECT / "contracts" / "e2-run-v03.json")
    old_abi = read_json(PROJECT / "contracts" / "representation-abi-v03.json")
    require(checks, "freeze_contract_hash_and_identity_bound", freeze.get("freeze_id") == "FAS_FROZEN_OBSERVER_BUNDLE_E0_FREEZE_V07" and freeze_hash == new_members[seal["freeze_contract_path"]]["sha256"])
    require(checks, "protocol_and_abi_hashes_bound", freeze.get("e2_v04_protocol_sha256") == protocol_hash and freeze.get("representation_abi_sha256") == abi_hash)
    require(checks, "verifier_and_extractor_hashes_bound_by_contract_and_abi", freeze.get("extractor_source_sha256") == abi.get("extractor_source_sha256") and freeze.get("execution_identity_verifier_sha256") == abi.get("execution_identity_verifier_sha256"))
    require(checks, "e0_e1_v01_identity_chain_preserved", freeze.get("predecessor_e0_root_sha256") == E0_V06_ROOT and seal.get("e1_v04_root_sha256") == E1_V04_ROOT and seal.get("e2_v01_preservation_root_sha256") == E2_V01_ROOT)
    require(checks, "all_authorities_remain_closed", all(freeze.get(key) is False for key in ("model_contact_authorized", "tokenizer_contact_authorized", "feature_extraction_authorized", "observer_fitting_authorized", "evaluation_scoring_authorized")) and all(protocol.get("authority", {}).get(key) is False for key in ("model_contact_authorized", "tokenizer_contact_authorized", "feature_extraction_authorized", "observer_fitting_authorized", "evaluation_scoring_authorized")))

    semantic_freeze_fields = (
        "starting_history", "panel_world_contract_path", "panel_world_contract_sha256", "task_endpoints",
        "performance_gates", "bootstrap", "observer_fit", "serving_workloads", "economics",
        "integration_parity", "representation_equivalence_gate", "program_boundary",
    )
    require(checks, "scientific_and_evaluation_contracts_unchanged", all(freeze.get(key) == old_freeze.get(key) for key in semantic_freeze_fields))
    normalized_limits = copy.deepcopy(freeze["resource_limits"])
    old_limits = copy.deepcopy(old_freeze["resource_limits"])
    for key in ("device_wide_preflight_path", "device_wide_postflight_path"):
        normalized_limits["gpu_measurement_protocol"][key] = old_limits["gpu_measurement_protocol"][key]
    require(checks, "resource_limits_unchanged_except_versioned_output_receipt_paths", normalized_limits == old_limits)

    require(checks, "abi_surface_loader_tokenization_and_runtime_preserved", all(abi.get(key) == old_abi.get(key) for key in ("model_id", "model_revision", "model_config_sha256", "model_weights_sha256", "model_asset_manifest_sha256", "tokenizer_id", "tokenizer_revision", "tokenizer_assets_manifest_sha256", "runtime_versions", "loader", "tokenization", "forward_call", "surface_id", "serialization_dtype", "feature_shape")))
    normalized_abi = copy.deepcopy(abi)
    for key in ("representation_abi_id", "predecessor_representation_abi_sha256", "extractor_source_path", "extractor_source_sha256", "execution_identity_verifier_path", "execution_identity_verifier_sha256", "resource_receipt_extension"):
        normalized_abi.pop(key, None)
    old_normalized_abi = copy.deepcopy(old_abi)
    for key in ("representation_abi_id", "predecessor_representation_abi_sha256", "extractor_source_path", "extractor_source_sha256", "resource_receipt_extension"):
        old_normalized_abi.pop(key, None)
    require(checks, "abi_delta_limited_to_versioned_source_identity_and_receipt_note", normalized_abi == old_normalized_abi)

    require(checks, "e2_protocol_identity_and_comparator_preserved", protocol.get("protocol_id") == "FAS_FROZEN_OBSERVER_BUNDLE_E2_RUN_V04" and protocol.get("representation_equivalence", {}).get("reference_cache_sha256") == REFERENCE_SHA256 and protocol.get("representation_equivalence", {}).get("reference_cache_bytes") == REFERENCE_BYTES and protocol.get("representation_equivalence", {}).get("gate") == old_protocol["representation_equivalence"]["gate"])
    require(checks, "e2_wait_gate_and_gpu_semantics_preserved", protocol.get("wait_gate", {}).get("target_process") == old_protocol["wait_gate"]["target_process"] and protocol.get("gpu_measurement", {}).get("total_gpu_memory_claimed") is False and protocol.get("gpu_measurement", {}).get("scope_claim_exact") == old_protocol["gpu_measurement"]["scope_claim_exact"] and protocol.get("gpu_measurement", {}).get("ceiling_bytes") == old_protocol["gpu_measurement"]["ceiling_bytes"])
    require(checks, "e2_panel_model_surface_repeat_and_shape_preserved", all(protocol.get("model_and_representation", {}).get(key) == old_protocol["model_and_representation"].get(key) for key in ("model_id", "revision", "read_only", "surface", "full_panel_rows", "hidden_dimension", "repeat_gate_rows", "representation_or_panel_change")))
    require(checks, "fresh_output_root_and_e3_authority_boundary", protocol.get("requires", {}).get("feature_output_root_must_be_new", "").endswith("\\e2-v04") and protocol.get("authority", {}).get("successful_e2_does_not_authorize_e3") is True)
    expected_identity = {
        "e1_root_sha256": E1_V04_ROOT,
        "extractor_source_sha256": abi.get("extractor_source_sha256"),
        "verifier_source_sha256": abi.get("execution_identity_verifier_sha256"),
        "representation_abi_sha256": abi_hash,
        "comparator_sha256": REFERENCE_SHA256,
    }
    require(checks, "normalized_execution_identity_fields_bound", protocol.get("execution_identity") == expected_identity)

    e2v02_stop = read_json(PROJECT / "audits" / "e2-v02-authorized-attempt-stop-v01.json")
    e2v03_stop = read_json(PROJECT / "audits" / "e2-v03-authorized-attempt-stop-v01.json")
    e2v03_auth = read_json(PROJECT / "audits" / "e2-v03-model-contact-authorization-v01.json")
    wait_path = PROJECT / "audits" / "e2-v02-concurrent-wait-complete-v01.json"
    require(checks, "prior_e2_attempts_remain_pre_contact_stops", e2v02_stop.get("model_contact_performed") is False and e2v03_stop.get("model_contact_performed") is False and e2v03_stop.get("cuda_allocator_initialized") is False)
    require(checks, "dead_v03_authorization_is_only_preserved_history", e2v03_auth.get("model_contact_authorized") is True and protocol.get("authority", {}).get("model_contact_authorized") is False)
    require(checks, "wait_receipt_hash_remains_bound", sha256_file(wait_path)[0] == protocol.get("wait_gate", {}).get("receipt_sha256"))

    audit = {
        "receipt_id": "FAS_FROZEN_OBSERVER_BUNDLE_E0_V07_INDEPENDENT_AUDIT_V01",
        "status": "E0_V07_INDEPENDENT_AUDIT_PASS_MODEL_CONTACT_NOT_AUTHORIZED",
        "recorded_utc": datetime.now(timezone.utc).isoformat(),
        "seal_path": str(SEAL_PATH.resolve()),
        "seal_root_sha256": seal["root_sha256"],
        "seal_entry_count": seal["entry_count"],
        "freeze_contract_sha256": freeze_hash,
        "e2_v04_protocol_sha256": protocol_hash,
        "representation_abi_sha256": abi_hash,
        "checks": checks,
        "all_checks_passed": all(checks.values()),
        "model_contact_authorized": False,
        "tokenizer_contact_authorized": False,
        "cuda_allocator_initialized": False,
        "e3_authorized": False,
    }
    if RECEIPT_PATH.exists():
        raise RuntimeError(f"refusing to overwrite independent audit receipt: {RECEIPT_PATH}")
    RECEIPT_PATH.write_text(json.dumps(audit, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": audit["status"], "root_sha256": seal["root_sha256"], "checks": checks}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
