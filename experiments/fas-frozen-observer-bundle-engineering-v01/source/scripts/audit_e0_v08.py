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
PREDECESSOR_ROOT = "0849d205a5df13c905619cd1612a7d94cfb9c380ce7519390b8702df5a83417b"
E1_ROOT = "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03"
E2_V01_ROOT = "0ff309d833cd87017f7384247e4420a508f582ad9f375c5637f586d73b703f4c"
REFERENCE_SHA256 = "8eb80df5f73e761fe6c025fc1c66abef2027d639b6c14f56d4177d6e6a7a45a4"
REFERENCE_BYTES = 872_415_232
STATUS = "E0_FROZEN_NOT_AUTHORIZED_FOR_MODEL_CONTACT"
SEAL_PATH = PROJECT / "seals" / "e0-seal-v08.json"
RECEIPT_PATH = PROJECT / "audits" / "e0-v08-independent-audit-v01.json"


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


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2) + "\n").encode("utf-8")


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
        raise RuntimeError(f"seal root or member count failed: {path.name}")
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
        raise RuntimeError(f"referenced contract differs from its sealed identity: {field}")
    return path, digest


def require(checks: dict[str, bool], name: str, condition: bool) -> None:
    checks[name] = bool(condition)
    if not condition:
        raise RuntimeError(f"independent E0 v08 audit failed: {name}")


def main() -> int:
    predecessor = verify_seal(PROJECT / "seals" / "e0-seal-v07.json", PREDECESSOR_ROOT)
    seal = verify_seal(SEAL_PATH)
    checks: dict[str, bool] = {}
    require(checks, "e0_v08_manifest_root_members_and_count_recomputed", True)
    require(checks, "no_metadata_alias_required_for_contract_identity", "freeze_id" not in seal)
    require(checks, "authority_closed_and_total_gpu_claim_false", seal.get("status") == STATUS and all(seal.get(key) is False for key in ("model_contact_authorized", "tokenizer_contact_authorized", "feature_extraction_authorized", "observer_fitting_authorized", "evaluation_scoring_authorized", "total_gpu_memory_claimed")))
    require(checks, "direct_predecessor_and_population_roots_bound", seal.get("predecessor_e0_root_sha256") == PREDECESSOR_ROOT and seal.get("e1_v04_root_sha256") == E1_ROOT and seal.get("e2_v01_preservation_root_sha256") == E2_V01_ROOT)

    old_members = {row["path"]: row for row in predecessor["entries"]}
    new_members = {row["path"]: row for row in seal["entries"]}
    require(checks, "all_e0_v07_members_carried_forward_byte_exact", all(new_members.get(path) == row for path, row in old_members.items()))
    required_members = {
        f"{PROJECT_REL}/audits/e0-v07-independent-audit-failure-v01.json",
        f"{PROJECT_REL}/contracts/e0-freeze-v08-sealed-v01.json",
        f"{PROJECT_REL}/contracts/e2-run-v05.json",
        f"{PROJECT_REL}/contracts/representation-abi-v05.json",
        f"{PROJECT_REL}/source/scripts/extract_features_v05.py",
        f"{PROJECT_REL}/source/scripts/e2_execution_identity_v05.py",
        f"{PROJECT_REL}/source/tests/test_e2_execution_identity_v05.py",
        f"{PROJECT_REL}/audits/e2-v02-authorized-attempt-stop-v01.json",
        f"{PROJECT_REL}/audits/e2-v03-authorized-attempt-stop-v01.json",
    }
    require(checks, "new_identity_failure_and_regression_sources_are_members", required_members <= new_members.keys())

    freeze_path, freeze_hash = member(seal, "freeze_contract_path")
    protocol_path, protocol_hash = member(seal, "e2_protocol_path")
    abi_path, abi_hash = member(seal, "representation_abi_path")
    freeze = read_json(freeze_path)
    protocol = read_json(protocol_path)
    abi = read_json(abi_path)
    old_freeze = read_json(PROJECT / "contracts" / "e0-freeze-v07-sealed-v01.json")
    old_protocol = read_json(PROJECT / "contracts" / "e2-run-v04.json")
    old_abi = read_json(PROJECT / "contracts" / "representation-abi-v04.json")
    failure_path = PROJECT / "audits" / "e0-v07-independent-audit-failure-v01.json"
    failure = read_json(failure_path)
    failure_hash = sha256_file(failure_path)[0]
    require(checks, "e0_v08_contract_hashes_match_exact_disk_bytes", freeze.get("e2_v05_protocol_sha256") == protocol_hash and freeze.get("representation_abi_sha256") == abi_hash and canonical_json(protocol) == protocol_path.read_bytes() and canonical_json(abi) == abi_path.read_bytes())
    require(checks, "e0_v07_failure_is_bound_and_preserved", failure.get("status") == "E0_V07_AUDIT_FAILED_PRESERVED_NO_MODEL_CONTACT" and failure.get("model_contact_performed") is False and freeze.get("amendment", {}).get("predecessor_e0_v07_independent_audit_failure_sha256") == failure_hash and seal.get("e0_v07_audit_failure_receipt_sha256") == failure_hash)
    require(checks, "freeze_and_protocol_are_v08_v05_closed_authority", freeze.get("freeze_id") == "FAS_FROZEN_OBSERVER_BUNDLE_E0_FREEZE_V08" and protocol.get("protocol_id") == "FAS_FROZEN_OBSERVER_BUNDLE_E2_RUN_V05" and all(protocol.get("authority", {}).get(key) is False for key in ("model_contact_authorized", "tokenizer_contact_authorized", "feature_extraction_authorized", "observer_fitting_authorized", "evaluation_scoring_authorized")))
    require(checks, "verifier_extractor_and_abi_source_hashes_match", freeze.get("extractor_source_sha256") == abi.get("extractor_source_sha256") and freeze.get("execution_identity_verifier_sha256") == abi.get("execution_identity_verifier_sha256"))

    stable_freeze_fields = (
        "starting_history", "panel_world_contract_path", "panel_world_contract_sha256", "task_endpoints",
        "performance_gates", "bootstrap", "observer_fit", "serving_workloads", "economics",
        "integration_parity", "representation_equivalence_gate", "program_boundary",
    )
    require(checks, "science_and_task_contract_unchanged", all(freeze.get(key) == old_freeze.get(key) for key in stable_freeze_fields))
    normalized_limits = copy.deepcopy(freeze["resource_limits"])
    old_limits = copy.deepcopy(old_freeze["resource_limits"])
    for key in ("device_wide_preflight_path", "device_wide_postflight_path"):
        normalized_limits["gpu_measurement_protocol"][key] = old_limits["gpu_measurement_protocol"][key]
    require(checks, "resource_semantics_unchanged_except_versioned_telemetry_paths", normalized_limits == old_limits)

    stable_abi_fields = (
        "model_id", "model_revision", "model_config_sha256", "model_weights_sha256", "model_asset_manifest_sha256",
        "tokenizer_id", "tokenizer_revision", "tokenizer_assets_manifest_sha256", "runtime_versions", "loader",
        "tokenization", "forward_call",
    )
    require(checks, "model_tokenizer_runtime_and_representation_abi_unchanged", all(abi.get(key) == old_abi.get(key) for key in stable_abi_fields))
    normalized_abi = copy.deepcopy(abi)
    for key in ("representation_abi_id", "predecessor_representation_abi_sha256", "extractor_source_path", "extractor_source_sha256", "execution_identity_verifier_path", "execution_identity_verifier_sha256", "resource_receipt_extension"):
        normalized_abi.pop(key, None)
    old_normalized_abi = copy.deepcopy(old_abi)
    for key in ("representation_abi_id", "predecessor_representation_abi_sha256", "extractor_source_path", "extractor_source_sha256", "execution_identity_verifier_path", "execution_identity_verifier_sha256", "resource_receipt_extension"):
        old_normalized_abi.pop(key, None)
    require(checks, "abi_change_limited_to_new_identity_hashes_and_receipt_note", normalized_abi == old_normalized_abi)

    require(checks, "e2_comparator_surface_rows_repeat_and_resource_ceiling_unchanged", protocol.get("representation_equivalence", {}).get("reference_cache_sha256") == REFERENCE_SHA256 and protocol.get("representation_equivalence", {}).get("reference_cache_bytes") == REFERENCE_BYTES and protocol.get("model_and_representation", {}).get("surface") == old_protocol["model_and_representation"]["surface"] and protocol.get("model_and_representation", {}).get("full_panel_rows") == old_protocol["model_and_representation"]["full_panel_rows"] and protocol.get("model_and_representation", {}).get("hidden_dimension") == old_protocol["model_and_representation"]["hidden_dimension"] and protocol.get("model_and_representation", {}).get("repeat_gate_rows") == old_protocol["model_and_representation"]["repeat_gate_rows"] and protocol.get("gpu_measurement", {}).get("ceiling_bytes") == old_protocol["gpu_measurement"]["ceiling_bytes"] and protocol.get("gpu_measurement", {}).get("total_gpu_memory_claimed") is False)
    require(checks, "wait_identity_and_e3_boundary_preserved", protocol.get("wait_gate", {}).get("target_process") == old_protocol["wait_gate"]["target_process"] and protocol.get("wait_gate", {}).get("receipt_sha256") == old_protocol["wait_gate"]["receipt_sha256"] and protocol.get("authority", {}).get("successful_e2_does_not_authorize_e3") is True)
    require(checks, "e2_fresh_output_root_and_identity_hash_fields_bound", protocol.get("preflight_paths", {}).get("feature_output_root", "").endswith("\\e2-v05") and protocol.get("predecessors", {}).get("e0_v07_root_sha256") == PREDECESSOR_ROOT and protocol.get("execution_identity", {}).get("representation_abi_sha256") == abi_hash and protocol.get("execution_identity", {}).get("extractor_source_sha256") == abi.get("extractor_source_sha256") and protocol.get("execution_identity", {}).get("verifier_source_sha256") == abi.get("execution_identity_verifier_sha256"))
    expected_gates = [item.replace("E2 v04", "E2 v05") for item in old_protocol["success_gates"]]
    expected_gates[0] = "current E0 v08 root and all member hashes, its sealed E0 v07 predecessor root and member hashes, and the E1 v04 root verify before importing model/tokenizer libraries"
    require(checks, "panel_economics_performance_and_stop_gates_carried", protocol.get("success_gates") == expected_gates and protocol.get("stop_and_preserve_conditions") == [item.replace("E2 v04", "E2 v05") for item in old_protocol["stop_and_preserve_conditions"]])

    for source_map in (freeze.get("frozen_source_sha256", {}), freeze.get("validation_source_sha256", {})):
        for relative, expected in source_map.items():
            path = REPO_ROOT / relative
            if not path.is_file():
                path = PROJECT / relative
            if not path.is_file() or sha256_file(path)[0] != expected:
                raise RuntimeError(f"frozen source or validator hash mismatch: {relative}")
    checks["all_frozen_and_validation_source_hashes_verified"] = True

    audit = {
        "receipt_id": "FAS_FROZEN_OBSERVER_BUNDLE_E0_V08_INDEPENDENT_AUDIT_V01",
        "status": "E0_V08_INDEPENDENT_AUDIT_PASS_MODEL_CONTACT_NOT_AUTHORIZED",
        "recorded_utc": datetime.now(timezone.utc).isoformat(),
        "seal_path": str(SEAL_PATH.resolve()),
        "seal_root_sha256": seal["root_sha256"],
        "seal_entry_count": seal["entry_count"],
        "freeze_contract_sha256": freeze_hash,
        "e2_v05_protocol_sha256": protocol_hash,
        "representation_abi_sha256": abi_hash,
        "preserved_e0_v07_audit_failure_sha256": failure_hash,
        "checks": checks,
        "all_checks_passed": all(checks.values()),
        "model_contact_authorized": False,
        "tokenizer_contact_authorized": False,
        "cuda_allocator_initialized": False,
        "e3_authorized": False,
    }
    if RECEIPT_PATH.exists():
        raise RuntimeError(f"refusing to overwrite independent audit receipt: {RECEIPT_PATH}")
    RECEIPT_PATH.write_bytes(canonical_json(audit))
    print(json.dumps({"status": audit["status"], "root_sha256": seal["root_sha256"], "checks": checks}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
