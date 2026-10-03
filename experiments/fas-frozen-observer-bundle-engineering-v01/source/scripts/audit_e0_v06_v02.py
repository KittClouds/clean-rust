from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT_REL = "experiments/fas-frozen-observer-bundle-engineering-v01"
PROJECT_ROOT = REPO_ROOT / PROJECT_REL
E0_V05_ROOT = "56ab898130ddae394f3fa12a00eccf2bf6e565fde9c58e56f93eb70dde4bd693"
E1_V04_ROOT = "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03"
E2_V01_ROOT = "0ff309d833cd87017f7384247e4420a508f582ad9f375c5637f586d73b703f4c"
REFERENCE_SHA256 = "8eb80df5f73e761fe6c025fc1c66abef2027d639b6c14f56d4177d6e6a7a45a4"
REFERENCE_BYTES = 872415232
STATUS = "E0_FROZEN_NOT_AUTHORIZED_FOR_MODEL_CONTACT"


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


def verify_manifest(seal_path: Path, expected_status: str, expected_root: str | None = None) -> dict[str, Any]:
    seal = read_json(seal_path)
    if seal.get("status") != expected_status:
        raise RuntimeError(f"unexpected seal status in {seal_path.name}: {seal.get('status')!r}")
    actual: list[dict[str, Any]] = []
    for row in seal["entries"]:
        relative = Path(row["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"unsafe sealed path: {row['path']}")
        digest, size = sha256_file(REPO_ROOT / relative)
        if digest != row["sha256"] or size != row["bytes"]:
            raise RuntimeError(f"sealed member changed: {row['path']}")
        actual.append({"path": relative.as_posix(), "bytes": size, "sha256": digest})
    root = tree_root(actual)
    if root != seal.get("root_sha256") or (expected_root is not None and root != expected_root):
        raise RuntimeError(f"manifest root mismatch in {seal_path.name}")
    if len(actual) != seal.get("entry_count"):
        raise RuntimeError(f"manifest entry count mismatch in {seal_path.name}")
    return seal


def normalize_extractor_v03(source: str) -> str:
    text = source
    text = text.replace(
        '    if authorization.get("e0_v05_predecessor_root_sha256") != EXPECTED_E0_V05_ROOT:\n'
        '        raise RuntimeError("authorization does not preserve the E0 v05 predecessor")\n',
        "",
        1,
    )
    text = text.replace(
        'EXPECTED_E0_V05_ROOT = "56ab898130ddae394f3fa12a00eccf2bf6e565fde9c58e56f93eb70dde4bd693"\n',
        "",
        1,
    )
    text = text.replace(
        'if parent_root != EXPECTED_E0_V05_ROOT:\n'
        '        raise RuntimeError("E0 v06 seal does not preserve its E0 v05 predecessor")',
        'if parent_root != EXPECTED_E0_V04_ROOT:\n'
        '        raise RuntimeError("E0 v05 seal does not preserve its E0 v04 predecessor")',
        1,
    )
    text = text.replace(
        '        "e0_v05_predecessor_root_sha256": EXPECTED_E0_V05_ROOT,\n',
        "",
        1,
    )
    text = text.replace(
        'if authorization.get("e0_v06_root_sha256") != e0_seal["root_sha256"]:',
        'if authorization.get("e0_v05_root_sha256") != e0_seal["root_sha256"]:',
        1,
    )
    reverse = (
        ("E0_FROZEN_NOT_AUTHORIZED_FOR_MODEL_CONTACT", "E0_V05_FROZEN_NOT_AUTHORIZED_FOR_MODEL_CONTACT"),
        ("FAS_FROZEN_OBSERVER_BUNDLE_E0_FREEZE_V06", "FAS_FROZEN_OBSERVER_BUNDLE_E0_FREEZE_V05"),
        ("FAS_FROZEN_OBSERVER_BUNDLE_REPRESENTATION_ABI_V03", "FAS_FROZEN_OBSERVER_BUNDLE_REPRESENTATION_ABI_V02"),
        ("FAS_FROZEN_OBSERVER_BUNDLE_E2_RUN_V03", "FAS_FROZEN_OBSERVER_BUNDLE_E2_RUN_V02"),
        ("FAS_FROZEN_OBSERVER_BUNDLE_E2_MODEL_CONTACT_AUTHORIZATION_V03", "FAS_FROZEN_OBSERVER_BUNDLE_E2_MODEL_CONTACT_AUTHORIZATION_V02"),
        ("E2_V03", "E2_V02"),
        ("E2 v03", "E2 v02"),
        ("E2 v02 requires the versioned representation ABI v03", "E2 v02 requires the versioned representation ABI v02"),
        ("E0 v06", "E0 v05"),
        ("feature-cache-receipt-v03.json", "feature-cache-receipt-v02.json"),
        ("allocator-preflight-stop-v03.json", "allocator-preflight-stop-v02.json"),
    )
    for old, new in reverse:
        text = text.replace(old, new)
    return text


def check_protocol_preservation(old: dict[str, Any], new: dict[str, Any]) -> dict[str, bool]:
    checks: dict[str, bool] = {}
    for key, value in old["predecessors"].items():
        checks[f"protocol_predecessor_{key}_unchanged"] = new["predecessors"].get(key) == value
    for key, value in old["requires"].items():
        if key == "sealed_e0_v05_root_sha256":
            continue
        expected = value
        if key == "feature_output_root_must_be_new":
            expected = r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e2-v03"
            checks["protocol_uses_fresh_v03_output_root"] = new["requires"].get(key) == expected
        else:
            checks[f"protocol_requires_{key}_unchanged"] = new["requires"].get(key) == expected
    checks["protocol_binds_v06_root_slot"] = new["requires"].get("sealed_e0_v06_root_sha256") is None
    checks["wait_process_identity_unchanged"] = new["wait_gate"]["target_process"] == old["wait_gate"]["target_process"]
    wait_new = copy.deepcopy(new["wait_gate"])
    wait_new["wait_before"] = old["wait_gate"]["wait_before"]
    checks["wait_gate_other_fields_unchanged"] = wait_new == old["wait_gate"]

    model_new = copy.deepcopy(new["model_and_representation"])
    model_new["representation_abi_path"] = old["model_and_representation"]["representation_abi_path"]
    model_new["representation_abi_sha256"] = old["model_and_representation"]["representation_abi_sha256"]
    model_new["extractor_source_path"] = old["model_and_representation"]["extractor_source_path"]
    model_new["extractor_source_sha256"] = old["model_and_representation"]["extractor_source_sha256"]
    checks["model_representation_except_new_source_bindings_unchanged"] = model_new == old["model_and_representation"]

    gpu_new = copy.deepcopy(new["gpu_measurement"])
    gpu_new["device_wide_preflight_path"] = old["gpu_measurement"]["device_wide_preflight_path"]
    gpu_new["device_wide_postflight_path"] = old["gpu_measurement"]["device_wide_postflight_path"]
    checks["gpu_resource_semantics_unchanged"] = gpu_new == old["gpu_measurement"]
    checks["resource_receipt_sources_unchanged"] = new["other_resource_receipts"]["sampler_source"] == old["other_resource_receipts"]["sampler_source"] and new["other_resource_receipts"]["sampler_source_sha256"] == old["other_resource_receipts"]["sampler_source_sha256"]
    for key in old["other_resource_receipts"]:
        if key == "storage":
            checks["storage_receipts_remain_same_scope"] = all(
                phrase in new["other_resource_receipts"][key]
                for phrase in ("D: free-space preflight and postflight", "read the pinned E2 v01 cache only as a hash comparator", "fresh e2-v03 output root")
            )
        elif key not in ("sampler_source", "sampler_source_sha256"):
            checks[f"other_resource_{key}_unchanged"] = new["other_resource_receipts"][key] == old["other_resource_receipts"][key]

    expected_success = [item.replace("E0 v05", "E0 v06").replace("E2 v02", "E2 v03") for item in old["success_gates"]]
    checks["all_success_gates_unchanged_except_identity_labels"] = new["success_gates"] == expected_success
    checks["all_stop_conditions_unchanged_except_identity_labels"] = new["stop_and_preserve_conditions"] == [item.replace("E2 v02", "E2 v03") for item in old["stop_and_preserve_conditions"]]
    eq_new = copy.deepcopy(new["representation_equivalence"])
    eq_old = copy.deepcopy(old["representation_equivalence"])
    for key in ("reference_role", "mismatch_disposition"):
        eq_new[key] = eq_new[key].replace("v03", "v02")
    eq_new["reference_check_timing"] = [item.replace("v03", "v02") for item in eq_new["reference_check_timing"]]
    checks["v01_comparator_identity_and_gate_unchanged"] = eq_new == eq_old
    checks["authority_stays_closed_for_fitting_and_scoring"] = new["authority"] == old["authority"]
    checks["total_gpu_memory_claimed_false"] = new["gpu_measurement"].get("total_gpu_memory_claimed") is False
    return checks


def check_abi_preservation(old: dict[str, Any], new: dict[str, Any]) -> bool:
    normalized = copy.deepcopy(new)
    normalized["representation_abi_id"] = old["representation_abi_id"]
    normalized["predecessor_representation_abi_sha256"] = old["predecessor_representation_abi_sha256"]
    normalized["extractor_source_path"] = old["extractor_source_path"]
    normalized["extractor_source_sha256"] = old["extractor_source_sha256"]
    normalized["resource_receipt_extension"] = old["resource_receipt_extension"]
    return normalized == old


def main() -> int:
    v05_seal = verify_manifest(PROJECT_ROOT / "seals" / "e0-seal-v05.json", STATUS, E0_V05_ROOT)
    v06_path = PROJECT_ROOT / "seals" / "e0-seal-v06.json"
    v06_seal = verify_manifest(v06_path, STATUS)
    v05_entries = {row["path"]: row for row in v05_seal["entries"]}
    v06_entries = {row["path"]: row for row in v06_seal["entries"]}
    if any(v06_entries.get(path) != row for path, row in v05_entries.items()):
        raise RuntimeError("E0 v06 did not preserve every E0 v05 sealed member byte-for-byte")
    if v06_seal.get("predecessor_e0_root_sha256") != E0_V05_ROOT:
        raise RuntimeError("E0 v06 direct predecessor root mismatch")
    if v06_seal.get("predecessor_e0_seal_manifest_sha256") != sha256_file(PROJECT_ROOT / "seals" / "e0-seal-v05.json")[0]:
        raise RuntimeError("E0 v06 predecessor seal manifest hash mismatch")
    if v06_seal.get("e1_v04_root_sha256") != E1_V04_ROOT or v06_seal.get("e2_v01_preservation_root_sha256") != E2_V01_ROOT:
        raise RuntimeError("E1 or E2 v01 predecessor root changed")

    freeze = read_json(PROJECT_ROOT / "contracts" / "e0-freeze-v06-sealed-v02.json")
    protocol_v02 = read_json(PROJECT_ROOT / "contracts" / "e2-run-v02-sealed-v02.json")
    protocol_v03 = read_json(PROJECT_ROOT / "contracts" / "e2-run-v03.json")
    abi_v02 = read_json(PROJECT_ROOT / "contracts" / "representation-abi-v02.json")
    abi_v03 = read_json(PROJECT_ROOT / "contracts" / "representation-abi-v03.json")
    if freeze.get("freeze_id") != "FAS_FROZEN_OBSERVER_BUNDLE_E0_FREEZE_V06" or freeze.get("status") != STATUS:
        raise RuntimeError("E0 v06 freeze identity or status mismatch")
    freeze_v01 = read_json(PROJECT_ROOT / "contracts" / "e0-freeze-v06.json")
    failure_path = PROJECT_ROOT / "audits" / "e0-v06-seal-attempt-failure-v01.json"
    failure = read_json(failure_path)
    if failure.get("root_produced") is not False or failure.get("seal_manifest_written") is not False:
        raise RuntimeError("E0 v06 sealer v01 failure was not preserved as pre-root")
    if v06_seal.get("freeze_contract_path") != f"{PROJECT_REL}/contracts/e0-freeze-v06-sealed-v02.json":
        raise RuntimeError("E0 v06 seal does not identify the final freeze contract v02")
    if freeze.get("seal_attempt_failure_receipt_sha256") != sha256_file(failure_path)[0]:
        raise RuntimeError("final freeze does not bind the preserved sealer v01 failure")

    normalized_freeze = copy.deepcopy(freeze)
    for key in (
        "preseal_version_history",
        "seal_contract_path",
        "seal_attempt_failure_receipt_path",
        "seal_attempt_failure_receipt_sha256",
        "fresh_e2_v03_authorization_required_after_independent_audit",
    ):
        normalized_freeze.pop(key, None)
    v02_sources = (
        f"{PROJECT_REL}/source/scripts/seal_e0_v06_v02.py",
        f"{PROJECT_REL}/source/scripts/audit_e0_v06_v02.py",
        f"{PROJECT_REL}/source/scripts/build_e0_v06_v02.py",
    )
    for key in v02_sources:
        normalized_freeze["frozen_source_sha256"].pop(key, None)
    normalized_freeze["validation_source_sha256"].pop(v02_sources[1], None)
    if normalized_freeze != freeze_v01:
        raise RuntimeError("final freeze v02 changed E0 v06 substantive fields beyond provenance and helper bindings")
    for relative, expected in freeze.get("frozen_source_sha256", {}).items():
        if sha256_file(REPO_ROOT / relative)[0] != expected:
            raise RuntimeError(f"frozen source hash mismatch: {relative}")
    for relative, expected in freeze.get("validation_source_sha256", {}).items():
        if sha256_file(REPO_ROOT / relative)[0] != expected:
            raise RuntimeError(f"validation source hash mismatch: {relative}")

    if freeze.get("e0_v05_predecessor_root_sha256") != E0_V05_ROOT:
        raise RuntimeError("freeze contract does not bind E0 v05 as direct predecessor")
    if freeze.get("model_contact_authorized") is not False or freeze.get("tokenizer_contact_authorized") is not False:
        raise RuntimeError("E0 v06 accidentally authorizes model or tokenizer contact")
    if protocol_v03.get("protocol_id") != "FAS_FROZEN_OBSERVER_BUNDLE_E2_RUN_V03" or protocol_v03.get("status") != "E2_V03_FROZEN_NOT_AUTHORIZED":
        raise RuntimeError("E2 v03 protocol identity or authority mismatch")
    if abi_v03.get("representation_abi_id") != "FAS_FROZEN_OBSERVER_BUNDLE_REPRESENTATION_ABI_V03":
        raise RuntimeError("representation ABI v03 identity mismatch")

    extractor_v02 = (PROJECT_ROOT / "source" / "scripts" / "extract_features_v02.py").read_text(encoding="utf-8")
    extractor_v03 = (PROJECT_ROOT / "source" / "scripts" / "extract_features_v03.py").read_text(encoding="utf-8")
    if normalize_extractor_v03(extractor_v03) != extractor_v02:
        raise RuntimeError("E2 v03 extractor contains changes beyond the enumerated identity rebinding and status literal")
    if "E0_FROZEN_NOT_AUTHORIZED_FOR_MODEL_CONTACT" not in extractor_v03:
        raise RuntimeError("E2 v03 does not expect the exact sealed E0 status literal")
    protocol_checks = check_protocol_preservation(protocol_v02, protocol_v03)
    if not all(protocol_checks.values()):
        failed = sorted(key for key, value in protocol_checks.items() if not value)
        raise RuntimeError(f"E2 v03 changed frozen gates: {failed}")
    abi_unchanged = check_abi_preservation(abi_v02, abi_v03)
    if not abi_unchanged:
        raise RuntimeError("representation ABI v03 changed a model, tokenizer, runtime, surface, or serialization field")

    resource_v05 = copy.deepcopy(read_json(PROJECT_ROOT / "contracts" / "e0-freeze-v05-sealed-v02.json")["resource_limits"])
    resource_v06 = copy.deepcopy(freeze["resource_limits"])
    for key in ("device_wide_preflight_path", "device_wide_postflight_path"):
        resource_v06["gpu_measurement_protocol"][key] = resource_v05["gpu_measurement_protocol"][key]
    if resource_v05 != resource_v06:
        raise RuntimeError("E0 v06 changed substantive E0 v05 resource semantics")

    amendment = read_json(PROJECT_ROOT / "audits" / "e0-e2-compatibility-amendment-v06-v03-v01.json")
    if amendment.get("classification") != "contract-literal compatibility fix":
        raise RuntimeError("compatibility amendment is misclassified")
    stop = read_json(PROJECT_ROOT / "audits" / "e2-v02-authorized-attempt-stop-v01.json")
    if stop.get("status") != "STOPPED_BEFORE_MODEL_CONTACT_PRESERVE_AND_STOP" or stop.get("model_contact_performed") is not False:
        raise RuntimeError("E2 v02 stop attempt was not preserved accurately")
    if not (PROJECT_ROOT / "audits" / "e2-v02-model-contact-authorization-v01.json").is_file():
        raise RuntimeError("E2 v02 authorization history is missing")

    receipt = {
        "audit_id": "FAS_FROZEN_OBSERVER_BUNDLE_E0_V06_E2_V03_INDEPENDENT_AUDIT_V02",
        "status": "E0_V06_SEAL_AND_E2_V03_COMPATIBILITY_AUDIT_PASS_MODEL_CONTACT_NOT_AUTHORIZED",
        "e0_v05_root_sha256": E0_V05_ROOT,
        "e0_v06_root_sha256": v06_seal["root_sha256"],
        "e0_v06_entry_count": v06_seal["entry_count"],
        "e1_v04_root_sha256": E1_V04_ROOT,
        "e2_v01_preservation_root_sha256": E2_V01_ROOT,
        "e2_v02_stop_receipt_sha256": sha256_file(PROJECT_ROOT / "audits" / "e2-v02-authorized-attempt-stop-v01.json")[0],
        "checks": {
            "e0_v05_root_and_all_members_verified": True,
            "e0_v06_root_and_all_members_verified": True,
            "e0_v05_members_preserved_byte_for_byte": True,
            "e0_v05_stopped_attempt_and_authorization_preserved": True,
            "e0_v06_sealer_v01_pre_root_failure_preserved": True,
            "final_freeze_v02_substantive_fields_unchanged": True,
            "final_freeze_v02_source_bindings_verified": True,
            "e0_v06_direct_predecessor_is_e0_v05": True,
            "status_literal_matches_sealed_e0_value": True,
            "extractor_source_has_no_unlisted_changes": True,
            "resource_semantics_unchanged": True,
            "panel_model_tokenizer_representation_and_repeat_gates_unchanged": True,
            "exact_v01_comparator_and_gpu_scope_unchanged": True,
            "total_gpu_memory_claimed_false": True,
            "observer_fitting_scoring_and_model_contact_remain_unauthorized": True,
            **protocol_checks,
            "representation_abi_nonidentity_fields_unchanged": abi_unchanged,
        },
        "model_contact_authorized": False,
        "tokenizer_contact_authorized": False,
        "feature_extraction_authorized": False,
        "observer_fitting_authorized": False,
        "evaluation_scoring_authorized": False,
        "fresh_explicit_e2_v03_authorization_required": True,
    }
    out = PROJECT_ROOT / "audits" / "e0-v06-independent-audit-v02.json"
    if out.exists():
        raise RuntimeError(f"refusing to overwrite independent audit receipt: {out}")
    out.write_text(json.dumps(receipt, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(f"E0 v06 independent audit PASS: root_sha256={v06_seal['root_sha256']}; model_contact_authorized=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
