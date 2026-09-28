from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT_REL = PROJECT_ROOT.relative_to(REPO_ROOT).as_posix()
SEAL_PATH = PROJECT_ROOT / "seals" / "e0-seal-v05.json"
FREEZE_PATH = PROJECT_ROOT / "contracts" / "e0-freeze-v05-sealed-v02.json"
PROTOCOL_PATH = PROJECT_ROOT / "contracts" / "e2-run-v02-sealed-v02.json"
ABI_PATH = PROJECT_ROOT / "contracts" / "representation-abi-v02.json"
DRAFT_TREE_PATH = PROJECT_ROOT / "audits" / "e0-e2-draft-integrity-receipt-v08.json"
WAIT_PATH = PROJECT_ROOT / "audits" / "e2-v02-concurrent-wait-complete-v01.json"
AUDIT_PATH = PROJECT_ROOT / "audits" / "e0-v05-independent-seal-audit-v01.json"
EXPECTED_STATUS = "E0_FROZEN_NOT_AUTHORIZED_FOR_MODEL_CONTACT"
EXPECTED_FREEZE_REL = PROJECT_REL + "/contracts/e0-freeze-v05-sealed-v02.json"
EXPECTED_PROTOCOL_REL = PROJECT_REL + "/contracts/e2-run-v02-sealed-v02.json"
SEALER_RELATIVE_PATH = PROJECT_REL + "/source/scripts/seal_e0_v05_v02.py"
EXPECTED_WAIT_SHA256 = "b926124f9aa55b1b9fec2d794d0ac6a7a808128d43df9d53babb6cf143454b80"
EXPECTED_REFERENCE_SHA256 = "8eb80df5f73e761fe6c025fc1c66abef2027d639b6c14f56d4177d6e6a7a45a4"
EXPECTED_REFERENCE_BYTES = 872_415_232
EXPECTED_E2_V01_ROOT = "0ff309d833cd87017f7384247e4420a508f582ad9f375c5637f586d73b703f4c"
EXPECTED_E1_V04_ROOT = "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03"
GPU_SCOPE_CLAIM = (
    "E2 GPU gate = extractor-process PyTorch CUDA caching-allocator reserved peak; "
    "not total GPU memory used by E2."
)


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb", buffering=0) as stream:
        while chunk := stream.read(8 << 20):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected a JSON object: {path}")
    return value


def tree_root(entries: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in sorted(entries, key=lambda item: item["path"]):
        digest.update(f'{row["path"]}\t{row["bytes"]}\t{row["sha256"]}\n'.encode("utf-8"))
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    seal = read_json(SEAL_PATH)
    freeze = read_json(FREEZE_PATH)
    protocol = read_json(PROTOCOL_PATH)
    abi = read_json(ABI_PATH)
    draft_tree = read_json(DRAFT_TREE_PATH)
    entries = seal.get("entries", [])
    by_path = {row["path"]: row for row in entries}
    require(len(by_path) == len(entries), "seal contains duplicate entry paths")
    for row in entries:
        relative = Path(row["path"])
        require(not relative.is_absolute() and ".." not in relative.parts, "seal entry escapes repository root")
        digest, size = sha256_file(REPO_ROOT / relative)
        require(digest == row["sha256"] and size == row["bytes"], f"seal entry changed: {relative.as_posix()}")

    computed_root = tree_root(entries)
    require(computed_root == seal.get("root_sha256"), "E0 v05 seal root mismatch")
    require(seal.get("entry_count") == len(entries), "E0 v05 seal entry count mismatch")
    require(seal.get("seal_id") == "FAS_FROZEN_OBSERVER_BUNDLE_E0_SEAL_V05", "wrong E0 seal identity")
    require(seal.get("status") == EXPECTED_STATUS, "wrong E0 v05 sealed state")
    require(seal.get("freeze_contract_path") == EXPECTED_FREEZE_REL, "seal does not name the final v05 freeze")
    require(seal.get("e2_protocol_path") == EXPECTED_PROTOCOL_REL, "seal does not name the frozen v02 protocol")
    require(seal.get("predecessor_e0_root_sha256") == "fef50e3d7efe6ff35adf671940ee73112caf8ba6192596094aa6bb3e69ae9ab2",
            "seal predecessor root mismatch")
    require(EXPECTED_FREEZE_REL in by_path, "seal omits the intended E0 v05 freeze file")
    require(EXPECTED_PROTOCOL_REL in by_path, "seal omits the frozen E2 v02 protocol")
    require(PROJECT_REL + "/contracts/e0-freeze-v02.json" not in by_path, "seal repeats the historical v02 membership defect")

    freeze_sha, _ = sha256_file(FREEZE_PATH)
    protocol_sha, _ = sha256_file(PROTOCOL_PATH)
    abi_sha, _ = sha256_file(ABI_PATH)
    extractor_path = REPO_ROOT / Path(freeze["extractor_source_path"])
    extractor_sha, _ = sha256_file(extractor_path)
    require(by_path[EXPECTED_FREEZE_REL]["sha256"] == freeze_sha, "seal binds different E0 freeze bytes")
    require(freeze.get("freeze_id") == "FAS_FROZEN_OBSERVER_BUNDLE_E0_FREEZE_V05", "freeze ID is not v05")
    require(freeze.get("status") == EXPECTED_STATUS, "freeze status is not sealed-not-authorized")
    require(freeze.get("model_contact_authorized") is False and freeze.get("tokenizer_contact_authorized") is False,
            "E0 freeze grants model or tokenizer contact")
    require(freeze.get("feature_extraction_authorized") is False and freeze.get("observer_fitting_authorized") is False,
            "E0 freeze grants extraction or fitting")
    require(freeze.get("e2_v02_protocol_path") == EXPECTED_PROTOCOL_REL, "E0 freeze points at the wrong E2 contract")
    require(freeze.get("e2_v02_protocol_sha256") == protocol_sha, "E0 freeze's E2 protocol hash is wrong")
    require(by_path[EXPECTED_PROTOCOL_REL]["sha256"] == protocol_sha, "seal binds different E2 protocol bytes")
    require(protocol.get("status") == "E2_V02_FROZEN_NOT_AUTHORIZED", "E2 protocol is not frozen without authorization")
    require(protocol.get("protocol_id") == "FAS_FROZEN_OBSERVER_BUNDLE_E2_RUN_V02", "wrong E2 protocol ID")
    require(protocol.get("authority", {}).get("model_contact_authorized") is False, "E2 protocol authorizes model contact")
    require(protocol.get("authority", {}).get("feature_extraction_authorized") is False, "E2 protocol authorizes extraction")

    require(freeze.get("representation_abi_sha256") == abi_sha, "E0 freeze ABI hash mismatch")
    require(by_path[PROJECT_REL + "/contracts/representation-abi-v02.json"]["sha256"] == abi_sha,
            "seal does not bind ABI v02 bytes")
    require(abi.get("extractor_source_sha256") == extractor_sha, "ABI v02 extractor source hash mismatch")
    require(freeze.get("extractor_source_sha256") == extractor_sha, "E0 freeze extractor source hash mismatch")
    require(protocol.get("model_and_representation", {}).get("extractor_source_sha256") == extractor_sha,
            "E2 protocol extractor source hash mismatch")
    require(protocol.get("model_and_representation", {}).get("representation_abi_sha256") == abi_sha,
            "E2 protocol ABI hash mismatch")
    require(freeze.get("frozen_source_sha256", {}).get(
        "experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/seal_e0_v05_v02.py"
    ) == by_path[SEALER_RELATIVE_PATH]["sha256"], "E0 freeze sealer source hash mismatch")

    gpu = freeze["resource_limits"]["gpu_measurement_protocol"]
    protocol_gpu = protocol["gpu_measurement"]
    require(gpu.get("scope_claim_exact") == GPU_SCOPE_CLAIM, "E0 GPU scope claim mismatch")
    require(protocol_gpu.get("scope_claim_exact") == GPU_SCOPE_CLAIM, "E2 GPU scope claim mismatch")
    require(gpu.get("total_gpu_memory_claimed") is False, "E0 contract overclaims total GPU memory")
    require(protocol_gpu.get("total_gpu_memory_claimed") is False, "E2 contract overclaims total GPU memory")
    require(protocol_gpu.get("terminal_receipt_required_values") == {"total_gpu_memory_claimed": False},
            "E2 terminal receipt does not bind total_gpu_memory_claimed=false")

    wait_sha, _ = sha256_file(WAIT_PATH)
    require(wait_sha == EXPECTED_WAIT_SHA256, "S12 wait receipt hash changed")
    require(seal.get("wait_receipt_sha256") == wait_sha, "E0 seal wait-receipt hash mismatch")
    require(freeze.get("concurrent_gpu_wait_gate", {}).get("receipt_sha256") == wait_sha,
            "E0 freeze does not bind the completed wait receipt")
    wait = read_json(WAIT_PATH)
    require(wait.get("status") == "WAIT_COMPLETE_STABLE_ABSENCE", "S12 wait is not complete")
    require(wait.get("model_contact_performed_by_waiter") is False, "wait process performed model contact")
    require(wait.get("matching_script_processes_at_final_sample") == [], "S12 process remained at final sample")

    equivalence = protocol["representation_equivalence"]
    reference_path = Path(equivalence["reference_cache_path"])
    reference_sha, reference_size = sha256_file(reference_path)
    require(reference_sha == EXPECTED_REFERENCE_SHA256, "E2 v01 comparator cache hash mismatch")
    require(reference_size == EXPECTED_REFERENCE_BYTES, "E2 v01 comparator cache length mismatch")
    require(equivalence.get("reference_cache_sha256") == reference_sha, "E2 protocol comparator hash mismatch")
    require(equivalence.get("reference_cache_bytes") == reference_size, "E2 protocol comparator length mismatch")
    require(seal.get("e2_v01_reference_cache", {}).get("sha256") == reference_sha,
            "seal comparator-cache hash mismatch")
    require(seal.get("e2_v01_reference_cache", {}).get("bytes") == reference_size,
            "seal comparator-cache length mismatch")
    require(seal.get("e2_v01_preservation_root_sha256") == EXPECTED_E2_V01_ROOT,
            "seal does not bind the preserved E2 v01 root")
    require(freeze.get("amendment", {}).get("e2_v01_preservation_root_sha256_preserved") == EXPECTED_E2_V01_ROOT,
            "freeze does not bind the preserved E2 v01 root")
    require(seal.get("e1_v04_root_sha256") == EXPECTED_E1_V04_ROOT, "seal E1 v04 root mismatch")

    draft_root = tree_root(draft_tree.get("entries", []))
    draft_receipt_sha, _ = sha256_file(DRAFT_TREE_PATH)
    require(draft_root == draft_tree.get("draft_tree_sha256"), "v08 draft tree root mismatch")
    require(seal.get("reviewed_draft_tree_root_sha256") == draft_root, "seal v08 root mismatch")
    reviewed = freeze.get("reviewed_draft_tree", {})
    require(reviewed.get("tree_root_sha256") == draft_root, "freeze v08 root mismatch")
    require(reviewed.get("receipt_sha256") == draft_receipt_sha, "freeze v08 receipt hash mismatch")
    require(by_path[PROJECT_REL + "/audits/e0-e2-draft-integrity-receipt-v08.json"]["sha256"] == draft_receipt_sha,
            "seal omits or changes the v08 receipt manifest")
    for row in draft_tree["entries"]:
        relative = PROJECT_REL + "/" + row["path"]
        require(relative in by_path, f"seal omitted v08 draft-tree member: {row['path']}")
        require(by_path[relative]["sha256"] == row["sha256"], f"seal changed v08 draft-tree member: {row['path']}")
        require(by_path[relative]["bytes"] == row["bytes"], f"seal changed v08 draft-tree length: {row['path']}")

    failure_receipt_rel = PROJECT_REL + "/audits/e0-v05-seal-attempt-failure-v01.json"
    require(failure_receipt_rel in by_path, "seal omits the preserved failed seal-attempt receipt")
    failure_receipt = read_json(REPO_ROOT / Path(failure_receipt_rel))
    require(failure_receipt.get("seal_manifest_created") is False, "failed seal receipt misstates its outcome")
    require(failure_receipt.get("not_a_seal") is True, "failed seal receipt has an invalid disposition")

    require(seal.get("model_contact_authorized") is False, "seal grants model contact")
    require(seal.get("tokenizer_contact_authorized") is False, "seal grants tokenizer contact")
    require(seal.get("feature_extraction_authorized") is False, "seal grants extraction")
    require(seal.get("observer_fitting_authorized") is False, "seal grants observer fitting")
    require(not AUDIT_PATH.exists(), f"refusing to overwrite audit receipt: {AUDIT_PATH}")

    audit = {
        "audit_id": "FAS_FROZEN_OBSERVER_BUNDLE_E0_V05_INDEPENDENT_SEAL_AUDIT_V01",
        "status": "E0_V05_SEAL_INDEPENDENT_AUDIT_PASS_MODEL_CONTACT_NOT_AUTHORIZED",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "seal_path": PROJECT_REL + "/seals/e0-seal-v05.json",
        "seal_root_sha256": computed_root,
        "seal_entry_count": len(entries),
        "freeze_contract_path": EXPECTED_FREEZE_REL,
        "freeze_contract_sha256": freeze_sha,
        "e2_protocol_path": EXPECTED_PROTOCOL_REL,
        "e2_protocol_sha256": protocol_sha,
        "reviewed_v08_draft_tree_root_sha256": draft_root,
        "checks": {
            "all_manifest_file_hashes_and_lengths": True,
            "canonical_entry_tree_root": True,
            "v05_freeze_included_as_declared_freeze_contract": True,
            "historical_v02_membership_defect_absent": True,
            "e2_v02_protocol_frozen_but_not_authorized": True,
            "representation_abi_v02_hash_and_extractor_binding": True,
            "wait_receipt_hash_and_completed_status": True,
            "e2_v01_preservation_root": True,
            "e2_v01_comparator_cache_hash_and_length": True,
            "total_gpu_memory_claimed_false": True,
            "full_v08_draft_tree_and_manifest_included": True,
            "model_tokenizer_contact_or_extraction_performed": False,
        },
        "e2_v01_reference_cache": {
            "sha256": reference_sha,
            "bytes": reference_size,
            "role": "read-only comparator only; not eligible for fitting",
        },
        "model_contact_authorized": False,
        "tokenizer_contact_authorized": False,
        "feature_extraction_authorized": False,
        "observer_fitting_authorized": False,
        "not_an_e2_authorization": True,
    }
    AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"E0 v05 independent seal audit PASS: root_sha256={computed_root}; entries={len(entries)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
