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
E0_V04_ROOT = "fef50e3d7efe6ff35adf671940ee73112caf8ba6192596094aa6bb3e69ae9ab2"
E1_V04_ROOT = "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03"
E2_V01_ROOT = "0ff309d833cd87017f7384247e4420a508f582ad9f375c5637f586d73b703f4c"
E2_V01_CACHE_SHA256 = "8eb80df5f73e761fe6c025fc1c66abef2027d639b6c14f56d4177d6e6a7a45a4"
E2_V01_CACHE_BYTES = 872415232
E2_V02_STOP_PATH = PROJECT_ROOT / "audits" / "e2-v02-authorized-attempt-stop-v01.json"
E0_V05_SEAL = PROJECT_ROOT / "seals" / "e0-seal-v05.json"
E0_V05_FREEZE = PROJECT_ROOT / "contracts" / "e0-freeze-v05-sealed-v02.json"
E2_V02_PROTOCOL = PROJECT_ROOT / "contracts" / "e2-run-v02-sealed-v02.json"
ABI_V02 = PROJECT_ROOT / "contracts" / "representation-abi-v02.json"
EXTRACTOR_V02 = PROJECT_ROOT / "source" / "scripts" / "extract_features_v02.py"
FREEZE_V06 = PROJECT_ROOT / "contracts" / "e0-freeze-v06.json"
PROTOCOL_V03 = PROJECT_ROOT / "contracts" / "e2-run-v03.json"
ABI_V03 = PROJECT_ROOT / "contracts" / "representation-abi-v03.json"
EXTRACTOR_V03 = PROJECT_ROOT / "source" / "scripts" / "extract_features_v03.py"
AMENDMENT = PROJECT_ROOT / "audits" / "e0-e2-compatibility-amendment-v06-v03-v01.json"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def write_exclusive(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2) + "\n").encode("utf-8")


def replace_one(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected exactly one {label} source token, found {count}")
    return text.replace(old, new, 1)


def transform_extractor_v03(source: str) -> str:
    """Rebind v02 to v03 identities and correct the E0 status literal only."""
    text = source
    for old, new in (("E2_V02", "E2_V03"), ("E2 v02", "E2 v03"), ("E0 v05", "E0 v06")):
        if old not in text:
            raise RuntimeError(f"missing version label in extractor source: {old}")
        text = text.replace(old, new)
    for old, new in (
        ("FAS_FROZEN_OBSERVER_BUNDLE_E2_MODEL_CONTACT_AUTHORIZATION_V02", "FAS_FROZEN_OBSERVER_BUNDLE_E2_MODEL_CONTACT_AUTHORIZATION_V03"),
        ("FAS_FROZEN_OBSERVER_BUNDLE_E2_RUN_V02", "FAS_FROZEN_OBSERVER_BUNDLE_E2_RUN_V03"),
        ("FAS_FROZEN_OBSERVER_BUNDLE_REPRESENTATION_ABI_V02", "FAS_FROZEN_OBSERVER_BUNDLE_REPRESENTATION_ABI_V03"),
        ("feature-cache-receipt-v02.json", "feature-cache-receipt-v03.json"),
        ("allocator-preflight-stop-v02.json", "allocator-preflight-stop-v03.json"),
        ("E0_V05_FROZEN_NOT_AUTHORIZED_FOR_MODEL_CONTACT", "E0_FROZEN_NOT_AUTHORIZED_FOR_MODEL_CONTACT"),
        ("FAS_FROZEN_OBSERVER_BUNDLE_E0_FREEZE_V05", "FAS_FROZEN_OBSERVER_BUNDLE_E0_FREEZE_V06"),
        ("EXPECTED_E0_V04_ROOT = \"fef50e3d7efe6ff35adf671940ee73112caf8ba6192596094aa6bb3e69ae9ab2\"\n", "EXPECTED_E0_V04_ROOT = \"fef50e3d7efe6ff35adf671940ee73112caf8ba6192596094aa6bb3e69ae9ab2\"\nEXPECTED_E0_V05_ROOT = \"56ab898130ddae394f3fa12a00eccf2bf6e565fde9c58e56f93eb70dde4bd693\"\n"),
        ("    if authorization.get(\"e0_v04_predecessor_root_sha256\") != EXPECTED_E0_V04_ROOT:\n        raise RuntimeError(\"authorization does not preserve the E0 v04 predecessor\")\n", "    if authorization.get(\"e0_v04_predecessor_root_sha256\") != EXPECTED_E0_V04_ROOT:\n        raise RuntimeError(\"authorization does not preserve the E0 v04 predecessor\")\n    if authorization.get(\"e0_v05_predecessor_root_sha256\") != EXPECTED_E0_V05_ROOT:\n        raise RuntimeError(\"authorization does not preserve the E0 v05 predecessor\")\n"),
        ("if authorization.get(\"e0_v05_root_sha256\") != e0_seal[\"root_sha256\"]:\n", "if authorization.get(\"e0_v06_root_sha256\") != e0_seal[\"root_sha256\"]:\n"),
        ("E2 v03 requires the versioned representation ABI v02", "E2 v03 requires the versioned representation ABI v03"),
    ):
        if old not in text:
            raise RuntimeError(f"missing expected v02 source token: {old[:100]!r}")
        text = text.replace(old, new, 1)

    text = replace_one(
        text,
        "if parent_root != EXPECTED_E0_V04_ROOT:\n        raise RuntimeError(\"E0 v06 seal does not preserve its E0 v04 predecessor\")",
        "if parent_root != EXPECTED_E0_V05_ROOT:\n        raise RuntimeError(\"E0 v06 seal does not preserve its E0 v05 predecessor\")",
        "direct E0 predecessor pin",
    ) if "if parent_root != EXPECTED_E0_V04_ROOT:" in text else text

    # The old branch above may already have rebound the parent check. Keep the
    # original v04 field for lineage and bind the direct v05 predecessor too.
    text = text.replace(
        '"e0_v04_predecessor_root_sha256": EXPECTED_E0_V04_ROOT,\n',
        '"e0_v04_predecessor_root_sha256": EXPECTED_E0_V04_ROOT,\n        "e0_v05_predecessor_root_sha256": EXPECTED_E0_V05_ROOT,\n',
        1,
    )
    return text


def transform_protocol() -> dict[str, Any]:
    protocol = read_json(E2_V02_PROTOCOL)
    protocol["protocol_id"] = "FAS_FROZEN_OBSERVER_BUNDLE_E2_RUN_V03"
    protocol["status"] = "E2_V03_FROZEN_NOT_AUTHORIZED"
    predecessors = protocol["predecessors"]
    predecessors["e0_v05_root_sha256"] = E0_V05_ROOT
    predecessors["e2_v02_stop_receipt_path"] = f"{PROJECT_REL}/audits/e2-v02-authorized-attempt-stop-v01.json"
    predecessors["e2_v02_stop_receipt_sha256"] = sha256_file(E2_V02_STOP_PATH)[0]
    predecessors["e2_v02_disposition"] = "STOPPED_BEFORE_MODEL_CONTACT_PRESERVED; no tokenizer/model load, CUDA allocator initialization, or cache creation"

    requires = protocol["requires"]
    requires.pop("sealed_e0_v05_root_sha256", None)
    requires["sealed_e0_v06_root_sha256"] = None
    requires["feature_output_root_must_be_new"] = r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e2-v03"

    gate = protocol["wait_gate"]
    gate["wait_before"] = "runtime/model/tokenizer import or CUDA model contact in E2 v03"

    model = protocol["model_and_representation"]
    model["representation_abi_path"] = f"{PROJECT_REL}/contracts/representation-abi-v03.json"
    model["extractor_source_path"] = f"{PROJECT_REL}/source/scripts/extract_features_v03.py"
    model["representation_abi_sha256"] = "PENDING_ABI_HASH"
    model["extractor_source_sha256"] = "PENDING_EXTRACTOR_HASH"

    gpu = protocol["gpu_measurement"]
    gpu["device_wide_preflight_path"] = r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e2-v03\receipts\gpu-device-preflight-v03.csv"
    gpu["device_wide_postflight_path"] = r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e2-v03\receipts\gpu-device-postflight-v03.csv"

    storage = protocol["other_resource_receipts"]["storage"]
    protocol["other_resource_receipts"]["storage"] = storage.replace("v01 E2 attempt", "v01 and v02 E2 attempts").replace("v02 feature input", "v03 feature input").replace("e2-v02 output root", "e2-v03 output root")
    protocol["success_gates"] = [item.replace("E0 v05", "E0 v06").replace("E2 v02", "E2 v03") for item in protocol["success_gates"]]
    protocol["stop_and_preserve_conditions"] = [item.replace("E2 v02", "E2 v03") for item in protocol["stop_and_preserve_conditions"]]
    equivalence = protocol["representation_equivalence"]
    equivalence["reference_role"] = equivalence["reference_role"].replace("v02", "v03")
    equivalence["reference_check_timing"] = [item.replace("v02", "v03") for item in equivalence["reference_check_timing"]]
    equivalence["mismatch_disposition"] = equivalence["mismatch_disposition"].replace("v02", "v03")
    protocol["freeze_note"] = "Protocol bytes are frozen as part of E0 v06. This state does not authorize tokenizer or model contact."
    protocol["authority"]["successful_e2_does_not_authorize_e3"] = True
    return protocol


def build_abi(extractor_hash: str) -> dict[str, Any]:
    abi = read_json(ABI_V02)
    abi["representation_abi_id"] = "FAS_FROZEN_OBSERVER_BUNDLE_REPRESENTATION_ABI_V03"
    abi["predecessor_representation_abi_sha256"] = sha256_file(ABI_V02)[0]
    abi["extractor_source_path"] = f"{PROJECT_REL}/source/scripts/extract_features_v03.py"
    abi["extractor_source_sha256"] = extractor_hash
    abi["resource_receipt_extension"] = abi["resource_receipt_extension"].replace("E2 v02", "E2 v03")
    return abi


def build_freeze(protocol_hash: str, abi_hash: str, extractor_hash: str, amendment_hash: str) -> dict[str, Any]:
    freeze = read_json(E0_V05_FREEZE)
    freeze["freeze_id"] = "FAS_FROZEN_OBSERVER_BUNDLE_E0_FREEZE_V06"
    freeze["status"] = "E0_FROZEN_NOT_AUTHORIZED_FOR_MODEL_CONTACT"
    freeze["predecessor_e0_root_sha256"] = E0_V05_ROOT
    freeze["predecessor_e0_seal_manifest_sha256"] = sha256_file(E0_V05_SEAL)[0]
    freeze["e0_v04_ancestor_root_sha256"] = E0_V04_ROOT
    freeze["e0_v05_predecessor_root_sha256"] = E0_V05_ROOT
    freeze["representation_abi_path"] = f"{PROJECT_REL}/contracts/representation-abi-v03.json"
    freeze["representation_abi_sha256"] = abi_hash
    freeze["extractor_source_path"] = f"{PROJECT_REL}/source/scripts/extract_features_v03.py"
    freeze["extractor_source_sha256"] = extractor_hash
    freeze.pop("e2_v02_protocol_path", None)
    freeze.pop("e2_v02_protocol_sha256", None)
    freeze["e2_v03_protocol_path"] = f"{PROJECT_REL}/contracts/e2-run-v03.json"
    freeze["e2_v03_protocol_sha256"] = protocol_hash

    sources = dict(freeze["frozen_source_sha256"])
    for relative, path in (
        (f"{PROJECT_REL}/source/scripts/extract_features_v03.py", EXTRACTOR_V03),
        (f"{PROJECT_REL}/source/scripts/seal_e0_v06.py", PROJECT_ROOT / "source" / "scripts" / "seal_e0_v06.py"),
        (f"{PROJECT_REL}/source/scripts/audit_e0_v06.py", PROJECT_ROOT / "source" / "scripts" / "audit_e0_v06.py"),
        (f"{PROJECT_REL}/source/scripts/build_e0_v06.py", Path(__file__).resolve()),
    ):
        sources[relative] = sha256_file(path)[0]
    freeze["frozen_source_sha256"] = sources

    validation = dict(freeze.get("validation_source_sha256", {}))
    validation[f"{PROJECT_REL}/source/scripts/audit_e0_v06.py"] = sha256_file(PROJECT_ROOT / "source" / "scripts" / "audit_e0_v06.py")[0]
    freeze["validation_source_sha256"] = validation

    freeze["resource_limits"]["gpu_measurement_protocol"]["device_wide_preflight_path"] = r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e2-v03\receipts\gpu-device-preflight-v03.csv"
    freeze["resource_limits"]["gpu_measurement_protocol"]["device_wide_postflight_path"] = r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e2-v03\receipts\gpu-device-postflight-v03.csv"
    phases = freeze["phases"]
    phases["E0"] = "E0 v06 carries the narrowly versioned E2 contract compatibility correction; it remains sealed and unauthorized for model contact."
    phases["E2"] = phases["E2"].replace("E2 v02", "E2 v03").replace("E0 v05", "E0 v06")
    phases["E3"] = "Fit and score remain separately unauthorized; E2 v03 success does not grant E3."

    wait_gate = freeze["concurrent_gpu_wait_gate"]
    wait_gate["wait_before"] = "runtime/model/tokenizer import or CUDA model contact in E2 v03"
    equivalence = freeze["representation_equivalence_gate"]
    equivalence["gate_id"] = "E2_V03_EXACT_CACHE_EQUIVALENCE_TO_PRESERVED_E2_V01"
    equivalence["reference_role"] = equivalence["reference_role"].replace("v02", "v03")
    equivalence["mismatch_disposition"] = equivalence["mismatch_disposition"].replace("v02", "v03")

    old_amendment = copy.deepcopy(freeze["amendment"])
    freeze["amendment_history"] = list(freeze.get("amendment_history", [])) + [old_amendment]
    freeze["amendment"] = {
        "amendment_id": "FAS_FROZEN_OBSERVER_BUNDLE_E0_V06_E2_V03_STATUS_LITERAL_COMPATIBILITY_FIX",
        "predecessor_e0_root_sha256": E0_V05_ROOT,
        "predecessor_e0_seal_manifest_sha256": sha256_file(E0_V05_SEAL)[0],
        "e2_v02_stop_receipt_path": f"{PROJECT_REL}/audits/e2-v02-authorized-attempt-stop-v01.json",
        "e2_v02_stop_receipt_sha256": sha256_file(E2_V02_STOP_PATH)[0],
        "observed_literal": "E0_FROZEN_NOT_AUTHORIZED_FOR_MODEL_CONTACT",
        "incorrect_v02_expected_literal": "E0_V05_FROZEN_NOT_AUTHORIZED_FOR_MODEL_CONTACT",
        "cause": "E2 v02 extractor verifier expected a status literal different from the independently audited E0 v05 seal manifest.",
        "classification": "contract-literal compatibility fix; not model/runtime/resource failure",
        "semantic_gate_delta": "Correct the verifier expected E0 manifest status to the exact sealed value.",
        "scientific_design_changed": False,
        "e1_v04_panel_root_unchanged": E1_V04_ROOT,
        "e2_v01_preservation_root_unchanged": E2_V01_ROOT,
        "model_and_tokenizer_revision_or_hashes_changed": False,
        "representation_surface_or_pooling_changed": False,
        "dtype_or_serialization_changed": False,
        "row_order_or_panel_changed": False,
        "repeat_gate_changed": False,
        "gpu_resource_semantics_changed": False,
        "e2_v01_comparator_sha256": E2_V01_CACHE_SHA256,
        "e2_v01_comparator_bytes": E2_V01_CACHE_BYTES,
        "total_gpu_memory_claimed": False,
        "stop_on_mismatch_unchanged": True,
        "observer_fitting_or_scoring_authorized": False,
        "fresh_e2_v03_authorization_required_after_seal_and_audit": True,
        "new_model_contact_authorized_by_this_amendment": False,
        "new_source_and_contract_hashes_are_identity_rebindings": True,
        "representation_abi_sha256": abi_hash,
        "extractor_source_sha256": extractor_hash,
        "e2_v03_protocol_sha256": protocol_hash,
        "compatibility_amendment_receipt_sha256": amendment_hash,
    }
    freeze["execution_history"] = [
        {
            "identity": "E2 v02",
            "receipt_path": f"{PROJECT_REL}/audits/e2-v02-authorized-attempt-stop-v01.json",
            "status": "STOPPED_BEFORE_MODEL_CONTACT_PRESERVE_AND_STOP",
            "scientific_or_representation_execution_occurred": False,
        }
    ]
    for key in (
        "model_contact_authorized",
        "tokenizer_contact_authorized",
        "feature_extraction_authorized",
        "observer_fitting_authorized",
    ):
        freeze[key] = False
    return freeze


def main() -> int:
    outputs = (FREEZE_V06, PROTOCOL_V03, ABI_V03, EXTRACTOR_V03, AMENDMENT)
    for path in outputs:
        if path.exists():
            raise RuntimeError(f"refusing to overwrite versioned E0 v06/E2 v03 artifact: {path}")
    seal = read_json(E0_V05_SEAL)
    if seal.get("root_sha256") != E0_V05_ROOT:
        raise RuntimeError("E0 v05 seal root does not match the known preserved identity")
    stop = read_json(E2_V02_STOP_PATH)
    if stop.get("status") != "STOPPED_BEFORE_MODEL_CONTACT_PRESERVE_AND_STOP":
        raise RuntimeError("E2 v02 pre-contact stop receipt does not pass its preserved status")
    frozen_paths = seal["entries"]
    expected_source = f"{PROJECT_REL}/source/scripts/extract_features_v02.py"
    expected_abi = f"{PROJECT_REL}/contracts/representation-abi-v02.json"
    if not any(row["path"] == expected_source for row in frozen_paths):
        raise RuntimeError("E0 v05 does not bind the E2 v02 extractor source")
    if not any(row["path"] == expected_abi for row in frozen_paths):
        raise RuntimeError("E0 v05 does not bind representation ABI v02")

    source_bytes = EXTRACTOR_V02.read_bytes()
    source_text = source_bytes.decode("utf-8")
    extractor_text = transform_extractor_v03(source_text)
    extractor_bytes = extractor_text.encode("utf-8")
    extractor_hash = sha256_bytes(extractor_bytes)
    write_exclusive(EXTRACTOR_V03, extractor_bytes)

    protocol = transform_protocol()
    protocol["model_and_representation"]["extractor_source_sha256"] = extractor_hash
    protocol_bytes = json_bytes(protocol)
    protocol_hash = sha256_bytes(protocol_bytes)
    write_exclusive(PROTOCOL_V03, protocol_bytes)

    abi = build_abi(extractor_hash)
    abi_bytes = json_bytes(abi)
    abi_hash = sha256_bytes(abi_bytes)
    write_exclusive(ABI_V03, abi_bytes)
    protocol["model_and_representation"]["representation_abi_sha256"] = abi_hash
    protocol_bytes = json_bytes(protocol)
    protocol_hash = sha256_bytes(protocol_bytes)
    # Protocol is new and still unsealed; update its ABI digest before freezing.
    PROTOCOL_V03.write_bytes(protocol_bytes)

    amendment = {
        "receipt_id": "FAS_FROZEN_OBSERVER_BUNDLE_E0_V06_E2_V03_COMPATIBILITY_AMENDMENT_V01",
        "status": "DRAFT_READY_FOR_SEAL_AND_INDEPENDENT_AUDIT_NOT_AUTHORIZED_FOR_MODEL_CONTACT",
        "classification": "contract-literal compatibility fix",
        "predecessor": {
            "e0_v05_root_sha256": E0_V05_ROOT,
            "e2_v02_authorized_stop_receipt": f"{PROJECT_REL}/audits/e2-v02-authorized-attempt-stop-v01.json",
            "e2_v02_authorized_stop_receipt_sha256": sha256_file(E2_V02_STOP_PATH)[0],
        },
        "mismatch": {
            "e2_v02_expected_literal": "E0_V05_FROZEN_NOT_AUTHORIZED_FOR_MODEL_CONTACT",
            "sealed_e0_v05_actual_literal": "E0_FROZEN_NOT_AUTHORIZED_FOR_MODEL_CONTACT",
            "independent_e0_v05_audit": "E0_V05_SEAL_INDEPENDENT_AUDIT_PASS_MODEL_CONTACT_NOT_AUTHORIZED",
        },
        "repair": {
            "e2_v03_expected_literal": "E0_FROZEN_NOT_AUTHORIZED_FOR_MODEL_CONTACT",
            "direct_parent_root": E0_V05_ROOT,
            "new_e0_freeze_id": "FAS_FROZEN_OBSERVER_BUNDLE_E0_FREEZE_V06",
            "new_e2_protocol_id": "FAS_FROZEN_OBSERVER_BUNDLE_E2_RUN_V03",
            "new_representation_abi_id": "FAS_FROZEN_OBSERVER_BUNDLE_REPRESENTATION_ABI_V03",
            "extractor_source_sha256": extractor_hash,
            "protocol_sha256": protocol_hash,
            "abi_sha256": abi_hash,
        },
        "unchanged_frozen_invariants": [
            "E0 v05 substantive resource semantics and process-scoped PyTorch allocator meaning",
            "E1 v04 panel root and population",
            "LiquidAI/LFM2.5-1.2B-Base revision, model hashes, tokenizer revision, tokenizer hashes, and runtime versions",
            "V1_FINAL_POSITION, final unpadded token position, tensor/hook identity, no alternative pooling",
            "float32 hidden values serialized as C-order little-endian float32",
            "ordered E1 rows and whole-quartet split",
            "registered 256-row deterministic repeat",
            "10 GiB extractor-process PyTorch CUDA reserved-memory ceiling and clean allocator baselines",
            "E2 v01 comparator SHA-256 8eb80df5f73e761fe6c025fc1c66abef2027d639b6c14f56d4177d6e6a7a45a4 and length 872415232",
            "total_gpu_memory_claimed=false; nvidia-smi remains diagnostic only",
            "preserve-and-stop on every frozen gate failure, with no in-place repair or second run under one identity",
            "E3 fitting/scoring remains separately unauthorized",
        ],
        "authorization": {
            "model_contact_authorized": False,
            "tokenizer_contact_authorized": False,
            "feature_extraction_authorized": False,
            "observer_fitting_authorized": False,
            "fresh_explicit_e2_v03_authorization_required_after_seal_and_independent_audit": True,
        },
    }
    amendment_bytes = json_bytes(amendment)
    amendment_hash = sha256_bytes(amendment_bytes)
    write_exclusive(AMENDMENT, amendment_bytes)

    freeze = build_freeze(protocol_hash, abi_hash, extractor_hash, amendment_hash)
    write_exclusive(FREEZE_V06, json_bytes(freeze))
    print(
        "E0 v06/E2 v03 prepared: "
        f"extractor={extractor_hash}; abi={abi_hash}; protocol={protocol_hash}; "
        "model_contact_authorized=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
