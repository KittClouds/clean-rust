from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT_REL = "experiments/fas-frozen-observer-bundle-engineering-v01"
PROJECT = REPO_ROOT / PROJECT_REL
E0_V06_ROOT = "968e7da8d44e36e31de81e87bdf140e7d766100891cecb7bbf9b4be80e99b3ea"
E0_V08_ROOT = "a782f0baaf04b97c00c64f5c63a5b954ce0df1b2d1cf1665833c374d568a9bf4"
E1_ROOT = "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03"
E2_V01_ROOT = "0ff309d833cd87017f7384247e4420a508f582ad9f375c5637f586d73b703f4c"
REFERENCE_SHA256 = "8eb80df5f73e761fe6c025fc1c66abef2027d639b6c14f56d4177d6e6a7a45a4"
REFERENCE_BYTES = 872_415_232
WAIT_SHA256 = "b926124f9aa55b1b9fec2d794d0ac6a7a808128d43df9d53babb6cf143454b80"
E2_V03_STOP_SHA256 = "c9a0a3c571a338e626b12ebe2ae6c2b605adee31aa2aae80e2b37ef837e042d8"
E2_V03_AUTH_SHA256 = "6f881c13ab1a8d334431650904cc3eae6983947b38e6da1c078e98108ceee719"
E0_V08_AUDIT_FAILURE_SHA256 = "687776b0b8bf88b898f63cf3dd87088f3a1e65632ea002af243b12b9d60ae6f9"


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb", buffering=0) as stream:
        while chunk := stream.read(8 << 20):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2) + "\n").encode("utf-8")


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_canonical(path: Path, value: Any) -> None:
    path.write_bytes(canonical_json(value))


def repo_file(relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise RuntimeError(f"unsafe repository-relative path: {relative}")
    return REPO_ROOT / path


def main() -> int:
    if (PROJECT / "seals" / "e0-seal-v09.json").exists():
        raise RuntimeError("E0 v09 seal already exists; refusing to rewrite its inputs")
    failure_path = PROJECT / "audits" / "e0-v08-independent-audit-failure-v01.json"
    failure = load(failure_path)
    failure_hash = sha256_file(failure_path)[0]
    if failure.get("status") != "E0_V08_AUDIT_FAILED_PRESERVED_NO_MODEL_CONTACT" or failure.get("model_contact_performed") is not False:
        raise RuntimeError("E0 v08 audit failure is not preserved as a no-contact artifact")
    if E0_V08_AUDIT_FAILURE_SHA256 and failure_hash != E0_V08_AUDIT_FAILURE_SHA256:
        raise RuntimeError("E0 v08 audit failure receipt hash differs from the recorded identity")

    old_freeze = load(PROJECT / "contracts" / "e0-freeze-v08-sealed-v01.json")
    old_abi = load(PROJECT / "contracts" / "representation-abi-v05.json")
    old_protocol = load(PROJECT / "contracts" / "e2-run-v05.json")
    old_seal = load(PROJECT / "seals" / "e0-seal-v08.json")
    if old_seal.get("root_sha256") != E0_V08_ROOT or old_seal.get("model_contact_authorized") is not False:
        raise RuntimeError("E0 v08 predecessor seal identity or authority mismatch")
    wait_path = PROJECT / "audits" / "e2-v02-concurrent-wait-complete-v01.json"
    if sha256_file(wait_path)[0] != WAIT_SHA256:
        raise RuntimeError("preserved concurrent-run wait receipt hash changed")
    if sha256_file(PROJECT / "audits" / "e2-v03-authorized-attempt-stop-v01.json")[0] != E2_V03_STOP_SHA256:
        raise RuntimeError("preserved E2 v03 stop receipt hash changed")
    if sha256_file(PROJECT / "audits" / "e2-v03-model-contact-authorization-v01.json")[0] != E2_V03_AUTH_SHA256:
        raise RuntimeError("superseded E2 v03 authorization hash changed")

    extractor_rel = f"{PROJECT_REL}/source/scripts/extract_features_v06.py"
    verifier_rel = f"{PROJECT_REL}/source/scripts/e2_execution_identity_v06.py"
    test_rel = f"{PROJECT_REL}/source/tests/test_e2_execution_identity_v06.py"
    build_rel = f"{PROJECT_REL}/source/scripts/build_e0_v09.py"
    seal_rel = f"{PROJECT_REL}/source/scripts/seal_e0_v09.py"
    audit_rel = f"{PROJECT_REL}/source/scripts/audit_e0_v09.py"
    extractor_hash = sha256_file(repo_file(extractor_rel))[0]
    verifier_hash = sha256_file(repo_file(verifier_rel))[0]

    abi = copy.deepcopy(old_abi)
    abi.update(
        representation_abi_id="FAS_FROZEN_OBSERVER_BUNDLE_REPRESENTATION_ABI_V06",
        predecessor_representation_abi_sha256=sha256_file(PROJECT / "contracts" / "representation-abi-v05.json")[0],
        extractor_source_path=extractor_rel,
        extractor_source_sha256=extractor_hash,
        execution_identity_verifier_path=verifier_rel,
        execution_identity_verifier_sha256=verifier_hash,
        resource_receipt_extension=(
            "E2 v06 preserves the frozen V1_FINAL_POSITION representation and PyTorch process-allocator gate. "
            "This version binds the existing wait receipt digest and terminal status, and normalizes sealed identities "
            "by verified root/hash membership."
        ),
    )
    abi_bytes = canonical_json(abi)
    abi_hash = hashlib.sha256(abi_bytes).hexdigest()
    ABI_PATH = PROJECT / "contracts" / "representation-abi-v06.json"
    PROTOCOL_PATH = PROJECT / "contracts" / "e2-run-v06.json"
    FREEZE_PATH = PROJECT / "contracts" / "e0-freeze-v09-sealed-v01.json"
    SEAL_PATH = PROJECT / "seals" / "e0-seal-v09.json"

    old_paths = load(PROJECT / "audits" / "e2-v03-model-contact-authorization-v01.json")
    paths = {
        "repo_root": str(REPO_ROOT.resolve()),
        "e0_seal_manifest_path": str(SEAL_PATH.resolve()),
        "e1_run_root": old_paths["e1_run_root"],
        "e2_protocol_path": str(PROTOCOL_PATH.resolve()),
        "representation_abi_path": str(ABI_PATH.resolve()),
        "extractor_source_path": str(repo_file(extractor_rel).resolve()),
        "execution_identity_verifier_path": str(repo_file(verifier_rel).resolve()),
        "model_snapshot_root": old_paths["model_snapshot_root"],
        "tokenizer_snapshot_root": old_paths["tokenizer_snapshot_root"],
        "model_asset_manifest_path": old_paths["model_asset_manifest_path"],
        "tokenizer_asset_manifest_path": old_paths["tokenizer_asset_manifest_path"],
        "concurrent_run_wait_receipt_path": f"{PROJECT_REL}/audits/e2-v02-concurrent-wait-complete-v01.json",
        "reference_cache_path": old_paths["e2_v01_reference_cache_path"],
        "feature_output_root": r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e2-v06",
        "panel_inputs_relative_path": "panel/panel-inputs-v01.jsonl",
        "row_manifest_relative_path": "panel/row-manifest-v01.jsonl",
    }
    protocol = copy.deepcopy(old_protocol)
    protocol["protocol_id"] = "FAS_FROZEN_OBSERVER_BUNDLE_E2_RUN_V06"
    protocol["status"] = "E2_V06_FROZEN_NOT_AUTHORIZED"
    protocol["predecessors"].update(
        e0_v06_root_sha256=E0_V06_ROOT,
        e0_v08_root_sha256=E0_V08_ROOT,
        e0_v08_audit_failure_receipt_sha256=failure_hash,
        e1_v04_root_sha256=E1_ROOT,
        e2_v01_preservation_root_sha256=E2_V01_ROOT,
        e2_v03_authorization_sha256=E2_V03_AUTH_SHA256,
        e2_v03_stop_receipt_sha256=E2_V03_STOP_SHA256,
        e2_v03_disposition="STOPPED_PRE_MODEL_CONTACT_PRESERVED; no model/tokenizer runtime or CUDA allocator contact",
    )
    protocol["requires"]["feature_output_root_must_be_new"] = paths["feature_output_root"]
    protocol["requires"]["sealed_e0_v08_root_sha256"] = E0_V08_ROOT
    protocol["requires"].pop("sealed_e0_v07_root_sha256", None)
    protocol["wait_gate"]["wait_before"] = "model/tokenizer runtime import, CUDA initialization, or model contact in E2 v06"
    protocol["wait_gate"]["receipt_sha256"] = WAIT_SHA256
    protocol["wait_gate"]["receipt_status"] = "WAIT_COMPLETE_STABLE_ABSENCE"
    protocol["model_and_representation"].update(
        representation_abi_path=f"{PROJECT_REL}/contracts/representation-abi-v06.json",
        representation_abi_sha256=abi_hash,
        extractor_source_path=extractor_rel,
        extractor_source_sha256=extractor_hash,
    )
    protocol["gpu_measurement"]["device_wide_preflight_path"] = paths["feature_output_root"] + r"\receipts\gpu-device-preflight-v06.csv"
    protocol["gpu_measurement"]["device_wide_postflight_path"] = paths["feature_output_root"] + r"\receipts\gpu-device-postflight-v06.csv"
    protocol["gpu_measurement"]["total_gpu_memory_claimed"] = False
    protocol["other_resource_receipts"]["storage"] = (
        "re-run D: free-space preflight and postflight; preserve E1 and E2 v01-v05; "
        "read E2 v01 only as comparator; use a fresh e2-v06 output root"
    )
    protocol["representation_equivalence"]["reference_role"] = (
        "read-only hash comparator only; E2 v01 cache is not reused as v06 features and is not eligible for fitting"
    )
    protocol["representation_equivalence"]["reference_check_timing"] = [
        "before model/tokenizer contact", "after full v06 extraction"
    ]
    protocol["representation_equivalence"]["mismatch_disposition"] = (
        "preserve v06 cache and failure receipt, then stop; no tolerance comparison or in-place repair"
    )
    protocol["success_gates"] = [item.replace("E2 v05", "E2 v06") for item in protocol["success_gates"]]
    protocol["stop_and_preserve_conditions"] = [item.replace("E2 v05", "E2 v06") for item in protocol["stop_and_preserve_conditions"]]
    protocol["success_gates"][0] = (
        "current E0 v09 root and all member hashes, its sealed E0 v08 predecessor root and member hashes, "
        "and the E1 v04 root verify before importing model/tokenizer libraries"
    )
    protocol["execution_identity"] = {
        "e1_root_sha256": E1_ROOT,
        "extractor_source_sha256": extractor_hash,
        "verifier_source_sha256": verifier_hash,
        "representation_abi_sha256": abi_hash,
        "comparator_sha256": REFERENCE_SHA256,
    }
    protocol["preflight_paths"] = paths
    protocol["validation_source_sha256"] = sha256_file(repo_file(test_rel))[0]
    protocol["freeze_note"] = (
        "E2 v06 binds the wait receipt digest/status and uses normalized root/hash identity. "
        "Model, tokenizer, panel, representation, comparator, repeat, GPU, resource, and stop gates remain frozen; "
        "model/tokenizer contact is not authorized by this protocol."
    )
    protocol_bytes = canonical_json(protocol)
    protocol_hash = hashlib.sha256(protocol_bytes).hexdigest()

    freeze = copy.deepcopy(old_freeze)
    freeze["freeze_id"] = "FAS_FROZEN_OBSERVER_BUNDLE_E0_FREEZE_V09"
    freeze["frozen_utc_date"] = "2026-09-26"
    freeze["representation_abi_path"] = f"{PROJECT_REL}/contracts/representation-abi-v06.json"
    freeze["representation_abi_sha256"] = abi_hash
    freeze["extractor_source_path"] = extractor_rel
    freeze["extractor_source_sha256"] = extractor_hash
    freeze["execution_identity_verifier_path"] = verifier_rel
    freeze["execution_identity_verifier_sha256"] = verifier_hash
    freeze["e2_v06_protocol_path"] = f"{PROJECT_REL}/contracts/e2-run-v06.json"
    freeze["e2_v06_protocol_sha256"] = protocol_hash
    freeze["predecessor_e0_root_sha256"] = E0_V08_ROOT
    freeze["predecessor_e0_seal_manifest_sha256"] = sha256_file(PROJECT / "seals" / "e0-seal-v08.json")[0]
    freeze["seal_contract_path"] = f"{PROJECT_REL}/contracts/e0-freeze-v09-sealed-v01.json"
    freeze["fresh_e2_v06_authorization_required_after_independent_audit"] = True
    for key in ("model_contact_authorized", "tokenizer_contact_authorized", "feature_extraction_authorized", "observer_fitting_authorized", "evaluation_scoring_authorized"):
        freeze[key] = False
    freeze["phases"]["E0"] = "E0 v09 binds the exact wait receipt and normalized root/hash execution identity; model contact remains separately gated."
    freeze["phases"]["E2"] = "E2 v06 performs the single frozen extraction only after a fresh root-bound authorization."
    freeze["phases"]["E3"] = "Observer fitting and scoring remain separately unauthorized; E2 success does not authorize E3."
    freeze["resource_limits"]["gpu_measurement_protocol"]["device_wide_preflight_path"] = protocol["gpu_measurement"]["device_wide_preflight_path"]
    freeze["resource_limits"]["gpu_measurement_protocol"]["device_wide_postflight_path"] = protocol["gpu_measurement"]["device_wide_postflight_path"]
    freeze["concurrent_gpu_wait_gate"]["wait_before"] = protocol["wait_gate"]["wait_before"]
    freeze["amendment"] = {
        "amendment_id": "FAS_FROZEN_OBSERVER_BUNDLE_E0_V09_WAIT_RECEIPT_BINDING_AND_IDENTITY_NORMALIZATION",
        "predecessor_e0_root_sha256": E0_V08_ROOT,
        "predecessor_e0_v08_independent_audit_failure_sha256": failure_hash,
        "e0_v08_failure_classification": "E2 wait verifier required receipt digest and status fields absent from the protocol",
        "e2_v02_v03_stops_preserved": True,
        "repair": "bind the completed wait receipt SHA-256 and terminal status in the frozen protocol; normalize E0 manifest by verified member path and semantic root/hash identity",
        "science_or_representation_changed": False,
        "model_tokenizer_panel_comparator_repeatability_and_resource_semantics_unchanged": True,
        "process_scoped_gpu_metric": "PyTorch CUDA caching-allocator reserved peak for the extractor process; not total device GPU memory",
        "total_gpu_memory_claimed": False,
        "fresh_e2_v06_authorization_required_after_seal_and_audit": True,
    }
    freeze["execution_history"] = list(freeze.get("execution_history", [])) + [
        {"execution_id": "E0_V08_SEAL_AUDIT", "disposition": "AUDIT_FAILED_PRESERVED", "reason": "wait verifier contract omitted receipt digest and status"},
        {"execution_id": "E2_V06", "disposition": "FROZEN_NOT_AUTHORIZED", "reason": "awaiting full local pre-model compatibility tests and independent E0 v09 audit"},
    ]
    frozen = dict(freeze["frozen_source_sha256"])
    frozen[extractor_rel] = extractor_hash
    frozen[verifier_rel] = verifier_hash
    freeze["frozen_source_sha256"] = dict(sorted(frozen.items()))
    validation = dict(freeze.get("validation_source_sha256", {}))
    for relative in (test_rel, build_rel, seal_rel, audit_rel):
        validation[relative] = sha256_file(repo_file(relative))[0]
    freeze["validation_source_sha256"] = dict(sorted(validation.items()))

    write_canonical(ABI_PATH, abi)
    write_canonical(PROTOCOL_PATH, protocol)
    write_canonical(FREEZE_PATH, freeze)
    if sha256_file(ABI_PATH)[0] != abi_hash or sha256_file(PROTOCOL_PATH)[0] != protocol_hash:
        raise RuntimeError("canonical JSON writer readback differs from the precomputed contract hashes")
    print(json.dumps({
        "status": "E0_V09_CONTRACTS_BUILT_UNSEALED",
        "e2_v06_protocol_sha256": protocol_hash,
        "representation_abi_sha256": abi_hash,
        "extractor_source_sha256": extractor_hash,
        "verifier_source_sha256": verifier_hash,
        "freeze_contract_sha256": sha256_file(FREEZE_PATH)[0],
        "e0_v08_audit_failure_sha256": failure_hash,
        "model_contact_authorized": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
