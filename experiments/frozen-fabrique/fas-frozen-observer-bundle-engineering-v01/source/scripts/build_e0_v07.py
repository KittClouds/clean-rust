from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT_REL = "experiments/fas-frozen-observer-bundle-engineering-v01"
PROJECT = REPO_ROOT / PROJECT_REL
FREEZE_PATH = PROJECT / "contracts" / "e0-freeze-v07-sealed-v01.json"
ABI_PATH = PROJECT / "contracts" / "representation-abi-v04.json"
PROTOCOL_PATH = PROJECT / "contracts" / "e2-run-v04.json"
E0_V06_ROOT = "968e7da8d44e36e31de81e87bdf140e7d766100891cecb7bbf9b4be80e99b3ea"
E1_V04_ROOT = "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03"
E2_V01_ROOT = "0ff309d833cd87017f7384247e4420a508f582ad9f375c5637f586d73b703f4c"
REFERENCE_SHA256 = "8eb80df5f73e761fe6c025fc1c66abef2027d639b6c14f56d4177d6e6a7a45a4"
REFERENCE_BYTES = 872_415_232
WAIT_SHA256 = "b926124f9aa55b1b9fec2d794d0ac6a7a808128d43df9d53babb6cf143454b80"
E2_V03_STOP_SHA256 = "c9a0a3c571a338e626b12ebe2ae6c2b605adee31aa2aae80e2b37ef837e042d8"
E2_V03_AUTH_SHA256 = "6f881c13ab1a8d334431650904cc3eae6983947b38e6da1c078e98108ceee719"


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb", buffering=0) as stream:
        while chunk := stream.read(8 << 20):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def repo_file(relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise RuntimeError(f"unsafe repository-relative path: {relative}")
    return REPO_ROOT / path


def main() -> int:
    seal_path = PROJECT / "seals" / "e0-seal-v07.json"
    if seal_path.exists():
        raise RuntimeError(f"E0 v07 seal already exists; refusing to rewrite its inputs: {seal_path}")
    v06 = load(PROJECT / "contracts" / "e0-freeze-v06-sealed-v03.json")
    old_abi = load(PROJECT / "contracts" / "representation-abi-v03.json")
    old_protocol = load(PROJECT / "contracts" / "e2-run-v03.json")
    e2_v03_stop_path = PROJECT / "audits" / "e2-v03-authorized-attempt-stop-v01.json"
    e2_v03_auth_path = PROJECT / "audits" / "e2-v03-model-contact-authorization-v01.json"
    e2_v03_stop = load(e2_v03_stop_path)
    e2_v03_auth = load(e2_v03_auth_path)
    if (
        e2_v03_stop.get("status") != "STOPPED_PRE_MODEL_CONTACT_PRESERVE_AND_STOP"
        or e2_v03_stop.get("model_contact_performed") is not False
        or e2_v03_stop.get("tokenizer_contact_performed") is not False
        or e2_v03_stop.get("cuda_allocator_initialized") is not False
        or e2_v03_stop.get("feature_extraction_performed") is not False
    ):
        raise RuntimeError("E2 v03 pre-contact failure receipt is not preserved as a no-contact stop")
    if (
        e2_v03_auth.get("authorization_id") != "FAS_FROZEN_OBSERVER_BUNDLE_E2_MODEL_CONTACT_AUTHORIZATION_V03"
        or e2_v03_auth.get("e0_root_sha256") != E0_V06_ROOT
        or sha256_file(e2_v03_stop_path)[0] != E2_V03_STOP_SHA256
        or sha256_file(e2_v03_auth_path)[0] != E2_V03_AUTH_SHA256
    ):
        raise RuntimeError("E2 v03 stop or superseded authorization identity changed")

    extractor_rel = f"{PROJECT_REL}/source/scripts/extract_features_v04.py"
    verifier_rel = f"{PROJECT_REL}/source/scripts/e2_execution_identity_v04.py"
    test_rel = f"{PROJECT_REL}/source/tests/test_e2_execution_identity_v04.py"
    build_rel = f"{PROJECT_REL}/source/scripts/build_e0_v07.py"
    seal_rel = f"{PROJECT_REL}/source/scripts/seal_e0_v07.py"
    audit_rel = f"{PROJECT_REL}/source/scripts/audit_e0_v07.py"
    extractor_hash = sha256_file(repo_file(extractor_rel))[0]
    verifier_hash = sha256_file(repo_file(verifier_rel))[0]
    abi = copy.deepcopy(old_abi)
    abi.update(
        representation_abi_id="FAS_FROZEN_OBSERVER_BUNDLE_REPRESENTATION_ABI_V04",
        predecessor_representation_abi_sha256=sha256_file(PROJECT / "contracts" / "representation-abi-v03.json")[0],
        extractor_source_path=extractor_rel,
        extractor_source_sha256=extractor_hash,
        execution_identity_verifier_path=verifier_rel,
        execution_identity_verifier_sha256=verifier_hash,
        resource_receipt_extension=(
            "E2 v04 keeps the frozen representation surface and process-scoped PyTorch allocator measurement; "
            "the execution verifier now normalizes the actual sealed E0 manifest by verified membership and "
            "root/hash identities rather than metadata field spelling."
        ),
    )
    abi_hash = hashlib.sha256((json.dumps(abi, ensure_ascii=True, indent=2) + "\n").encode("utf-8")).hexdigest()

    prior_paths = e2_v03_auth
    repo_abs = str(REPO_ROOT.resolve())
    paths = {
        "repo_root": repo_abs,
        "e0_seal_manifest_path": str(seal_path.resolve()),
        "e1_run_root": prior_paths["e1_run_root"],
        "e2_protocol_path": str(PROTOCOL_PATH.resolve()),
        "representation_abi_path": str(ABI_PATH.resolve()),
        "extractor_source_path": str(repo_file(extractor_rel).resolve()),
        "execution_identity_verifier_path": str(repo_file(verifier_rel).resolve()),
        "model_snapshot_root": prior_paths["model_snapshot_root"],
        "tokenizer_snapshot_root": prior_paths["tokenizer_snapshot_root"],
        "model_asset_manifest_path": prior_paths["model_asset_manifest_path"],
        "tokenizer_asset_manifest_path": prior_paths["tokenizer_asset_manifest_path"],
        "concurrent_run_wait_receipt_path": f"{PROJECT_REL}/audits/e2-v02-concurrent-wait-complete-v01.json",
        "reference_cache_path": prior_paths["e2_v01_reference_cache_path"],
        "feature_output_root": r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e2-v04",
        "panel_inputs_relative_path": "panel/panel-inputs-v01.jsonl",
        "row_manifest_relative_path": "panel/row-manifest-v01.jsonl",
    }
    protocol = copy.deepcopy(old_protocol)
    protocol["protocol_id"] = "FAS_FROZEN_OBSERVER_BUNDLE_E2_RUN_V04"
    protocol["status"] = "E2_V04_FROZEN_NOT_AUTHORIZED"
    protocol["predecessors"].update(
        e0_v06_root_sha256=E0_V06_ROOT,
        e1_v04_root_sha256=E1_V04_ROOT,
        e2_v01_preservation_root_sha256=E2_V01_ROOT,
        e2_v02_stop_receipt_sha256=sha256_file(PROJECT / "audits" / "e2-v02-authorized-attempt-stop-v01.json")[0],
        e2_v03_authorization_sha256=E2_V03_AUTH_SHA256,
        e2_v03_stop_receipt_sha256=E2_V03_STOP_SHA256,
        e2_v03_disposition="STOPPED_PRE_MODEL_CONTACT_PRESERVED; no model or tokenizer libraries imported and no CUDA allocator initialized",
    )
    protocol["requires"]["feature_output_root_must_be_new"] = paths["feature_output_root"]
    protocol["requires"]["sealed_e0_v06_root_sha256"] = E0_V06_ROOT
    protocol["requires"]["new_explicit_user_model_contact_authorization"] = True
    protocol["wait_gate"]["wait_before"] = "model/tokenizer runtime import, CUDA initialization, or model contact in E2 v04"
    protocol["model_and_representation"].update(
        representation_abi_path=f"{PROJECT_REL}/contracts/representation-abi-v04.json",
        representation_abi_sha256=abi_hash,
        extractor_source_path=extractor_rel,
        extractor_source_sha256=extractor_hash,
    )
    protocol["gpu_measurement"]["device_wide_preflight_path"] = paths["feature_output_root"] + r"\receipts\gpu-device-preflight-v04.csv"
    protocol["gpu_measurement"]["device_wide_postflight_path"] = paths["feature_output_root"] + r"\receipts\gpu-device-postflight-v04.csv"
    protocol["gpu_measurement"]["total_gpu_memory_claimed"] = False
    protocol["other_resource_receipts"]["storage"] = (
        "re-run D: free-space preflight and postflight; preserve E1 and E2 v01-v03; "
        "read E2 v01 only as comparator; use a fresh e2-v04 output root"
    )
    protocol["representation_equivalence"]["reference_role"] = (
        "read-only hash comparator only; E2 v01 cache is not reused as v04 features and is not eligible for fitting"
    )
    protocol["representation_equivalence"]["reference_check_timing"] = [
        "before model/tokenizer contact", "after full v04 extraction"
    ]
    protocol["representation_equivalence"]["mismatch_disposition"] = (
        "preserve v04 cache and failure receipt, then stop; no tolerance comparison or in-place repair"
    )
    protocol["success_gates"] = [item.replace("E2 v03", "E2 v04") for item in protocol["success_gates"]]
    protocol["stop_and_preserve_conditions"] = [
        item.replace("E2 v03", "E2 v04") for item in protocol["stop_and_preserve_conditions"]
    ]
    protocol["execution_identity"] = {
        "e1_root_sha256": E1_V04_ROOT,
        "extractor_source_sha256": extractor_hash,
        "verifier_source_sha256": verifier_hash,
        "representation_abi_sha256": abi_hash,
        "comparator_sha256": REFERENCE_SHA256,
    }
    protocol["preflight_paths"] = paths
    protocol["validation_source_sha256"] = sha256_file(repo_file(test_rel))[0]
    protocol["freeze_note"] = (
        "E2 v04 preserves E0 v06 science/resource gates and only changes execution-identity normalization "
        "plus versioned source bindings. This frozen protocol does not authorize model/tokenizer contact."
    )
    protocol_hash = hashlib.sha256((json.dumps(protocol, ensure_ascii=True, indent=2) + "\n").encode("utf-8")).hexdigest()

    freeze = copy.deepcopy(v06)
    freeze["freeze_id"] = "FAS_FROZEN_OBSERVER_BUNDLE_E0_FREEZE_V07"
    freeze["frozen_utc_date"] = "2026-09-26"
    freeze["representation_abi_path"] = f"{PROJECT_REL}/contracts/representation-abi-v04.json"
    freeze["representation_abi_sha256"] = abi_hash
    freeze["extractor_source_path"] = extractor_rel
    freeze["extractor_source_sha256"] = extractor_hash
    freeze["execution_identity_verifier_path"] = verifier_rel
    freeze["execution_identity_verifier_sha256"] = verifier_hash
    freeze["e2_v04_protocol_path"] = f"{PROJECT_REL}/contracts/e2-run-v04.json"
    freeze["e2_v04_protocol_sha256"] = protocol_hash
    freeze["e2_v03_protocol_path"] = v06["e2_v03_protocol_path"]
    freeze["e2_v03_protocol_sha256"] = v06["e2_v03_protocol_sha256"]
    freeze["predecessor_e0_root_sha256"] = E0_V06_ROOT
    freeze["predecessor_e0_seal_manifest_sha256"] = sha256_file(PROJECT / "seals" / "e0-seal-v06.json")[0]
    freeze["seal_contract_path"] = f"{PROJECT_REL}/contracts/e0-freeze-v07-sealed-v01.json"
    freeze["fresh_e2_v04_authorization_required_after_independent_audit"] = True
    freeze["fresh_e2_v03_authorization_required_after_independent_audit"] = False
    freeze["model_contact_authorized"] = False
    freeze["tokenizer_contact_authorized"] = False
    freeze["feature_extraction_authorized"] = False
    freeze["observer_fitting_authorized"] = False
    freeze["evaluation_scoring_authorized"] = False
    freeze["phases"]["E0"] = "E0 v07 seals only the verifier-compatibility repair; model contact remains separately gated."
    freeze["phases"]["E2"] = "E2 v04 repeats the single frozen extraction only after a fresh root-bound authorization."
    freeze["phases"]["E3"] = "Observer fitting and evaluation scoring remain separately unauthorized; E2 success does not authorize E3."
    freeze["resource_limits"]["gpu_measurement_protocol"]["device_wide_preflight_path"] = protocol["gpu_measurement"]["device_wide_preflight_path"]
    freeze["resource_limits"]["gpu_measurement_protocol"]["device_wide_postflight_path"] = protocol["gpu_measurement"]["device_wide_postflight_path"]
    freeze["concurrent_gpu_wait_gate"]["wait_before"] = "model/tokenizer runtime import, CUDA initialization, or model contact in E2 v04"
    freeze["amendment"] = {
        "amendment_id": "FAS_FROZEN_OBSERVER_BUNDLE_E0_V07_EXECUTION_IDENTITY_NORMALIZATION",
        "predecessor_e0_root_sha256": E0_V06_ROOT,
        "e2_v02_stop_receipt_sha256": sha256_file(PROJECT / "audits" / "e2-v02-authorized-attempt-stop-v01.json")[0],
        "e2_v03_authorization_sha256": E2_V03_AUTH_SHA256,
        "e2_v03_stop_receipt_sha256": E2_V03_STOP_SHA256,
        "e2_v03_failure_classification": "pre-contact verifier design failure caused by redundant manifest metadata field requirement",
        "repair": "normalize verified manifest membership and semantic root/hash bindings into ExecutionIdentity; record metadata without using metadata spellings as independent identity gates",
        "science_or_representation_changed": False,
        "model_tokenizer_panel_comparator_repeatability_resource_semantics_unchanged": True,
        "total_gpu_memory_claimed": False,
        "stop_on_real_integrity_failure_unchanged": True,
        "fresh_e2_v04_authorization_required_after_seal_and_audit": True,
    }
    freeze["execution_history"] = list(freeze.get("execution_history", [])) + [
        {"execution_id": "E2_V02", "disposition": "STOPPED_PRE_MODEL_CONTACT_PRESERVED", "reason": "pre-model verifier status literal mismatch"},
        {"execution_id": "E2_V03", "disposition": "STOPPED_PRE_MODEL_CONTACT_PRESERVED", "reason": "pre-model verifier required absent top-level freeze_id metadata"},
        {"execution_id": "E2_V04", "disposition": "FROZEN_NOT_AUTHORIZED", "reason": "new normalized identity contract; awaiting explicit authorization after local preflight tests"},
    ]
    frozen_sources = dict(freeze["frozen_source_sha256"])
    frozen_sources[extractor_rel] = extractor_hash
    frozen_sources[verifier_rel] = verifier_hash
    freeze["frozen_source_sha256"] = dict(sorted(frozen_sources.items()))
    validation = dict(freeze.get("validation_source_sha256", {}))
    for relative in (test_rel, build_rel, seal_rel, audit_rel):
        validation[relative] = sha256_file(repo_file(relative))[0]
    freeze["validation_source_sha256"] = dict(sorted(validation.items()))

    write(ABI_PATH, abi)
    write(PROTOCOL_PATH, protocol)
    write(FREEZE_PATH, freeze)
    print(json.dumps({
        "status": "E0_V07_CONTRACTS_BUILT_UNSEALED",
        "e2_v04_protocol_sha256": protocol_hash,
        "representation_abi_sha256": abi_hash,
        "extractor_source_sha256": extractor_hash,
        "verifier_source_sha256": verifier_hash,
        "freeze_contract_sha256": sha256_file(FREEZE_PATH)[0],
        "model_contact_authorized": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
