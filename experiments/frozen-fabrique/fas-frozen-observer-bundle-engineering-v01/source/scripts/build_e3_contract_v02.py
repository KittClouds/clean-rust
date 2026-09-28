from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT = REPO_ROOT / "experiments" / "fas-frozen-observer-bundle-engineering-v01"
RUNS = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01")
E3_V01 = RUNS / "e3-v01"
E3_V02 = RUNS / "e3-v02"
USER_FIT_INSTRUCTION = (
    "Once that compatibility test passes, proceed to the real goal: model contact, "
    "extraction, cache equality, and then fitting."
)
USER_CONTINUATION = "Version failures, learn from them, and push."
EXPECTED_E0_ROOT = "899a131c09298fdafdcc6771ad01e8982857a1cd47900259800f97dd7bea7ccd"
EXPECTED_E1_ROOT = "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03"
EXPECTED_E2_ROOT = "a2e2aa76f77904665b9abfa2a22f609c05219d8bc64c537bed41f5c634d1da8a"


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


def write_json(path: Path, value: Any) -> bytes:
    encoded = (json.dumps(value, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
    path.write_bytes(encoded)
    return encoded


def main() -> int:
    old_contract_path = PROJECT / "contracts" / "e3-fit-v01.json"
    old_auth_path = PROJECT / "audits" / "e3-fit-authorization-v01.json"
    contract_path = PROJECT / "contracts" / "e3-fit-v02.json"
    authorization_path = PROJECT / "audits" / "e3-fit-authorization-v02.json"
    disposition_path = PROJECT / "audits" / "e3-v01-resource-gate-disposition-v01.json"
    if any(path.exists() for path in (contract_path, authorization_path, disposition_path)):
        raise RuntimeError("E3 v02 identity or v01 disposition already exists; refusing overwrite")
    if E3_V02.exists():
        raise RuntimeError(f"E3 v02 output root already exists; preserving it: {E3_V02}")

    old_contract_hash, _ = sha256_file(old_contract_path)
    old_auth = read_json(old_auth_path)
    old_contract = read_json(old_contract_path)
    old_receipt_path = E3_V01 / "e3-fit-receipt-v01.json"
    old_receipt_hash, old_receipt_bytes = sha256_file(old_receipt_path)
    old_fit_source = PROJECT / "source" / "scripts" / "fit_observers_e3_v01.py"
    old_fit_hash, _ = sha256_file(old_fit_source)
    if old_auth.get("contract_sha256") != old_contract_hash:
        raise RuntimeError("preserved E3 v01 authorization no longer matches its contract")
    if old_contract["predecessors"]["e0_v10_root_sha256"] != EXPECTED_E0_ROOT:
        raise RuntimeError("E3 v01 does not bind the expected frozen E0 root")
    if old_contract["predecessors"]["e1_v04_root_sha256"] != EXPECTED_E1_ROOT:
        raise RuntimeError("E3 v01 does not bind the expected sealed E1 root")
    if old_contract["predecessors"]["e2_v07_root_sha256"] != EXPECTED_E2_ROOT:
        raise RuntimeError("E3 v01 does not bind the expected sealed E2 root")

    disposition = {
        "receipt_id": "FAS_FROZEN_OBSERVER_BUNDLE_E3_V01_RESOURCE_GATE_DISPOSITION_V01",
        "status": "E3_V01_FITS_PRESERVED_RESOURCE_GATE_UNVERIFIED_NOT_QUALIFIED",
        "recorded_utc": datetime.now(timezone.utc).isoformat(),
        "e3_v01_contract_sha256": old_contract_hash,
        "e3_v01_fit_source_sha256": old_fit_hash,
        "e3_v01_fit_receipt_sha256": old_receipt_hash,
        "e3_v01_fit_receipt_bytes": old_receipt_bytes,
        "fit_artifacts_modified": False,
        "declared_minimum_free_disk_bytes": old_contract["resources"]["minimum_free_disk_bytes"],
        "disk_space_measured_before_fit": False,
        "historical_disk_gate_disposition": "UNVERIFIED; current free-space readings cannot qualify the earlier execution retroactively",
        "independent_findings": [
            "The E3 v01 contract declared a minimum free-disk resource gate.",
            "The E3 v01 fitter did not measure or record free disk before creating its output root.",
            "This is an engineering qualification gap, not a model-performance result.",
        ],
        "evaluation_labels_opened": False,
        "heldout_rows_read": False,
        "performance_scored": False,
        "superseded_by": "E3 v02 uses the same fit inputs, tasks, model, optimizer, and no-scoring boundary with the disk preflight implemented and receipted.",
    }
    disposition_bytes = write_json(disposition_path, disposition)
    disposition_hash = hashlib.sha256(disposition_bytes).hexdigest()

    fit_source = PROJECT / "source" / "scripts" / "fit_observers_e3_v02.py"
    test_source = PROJECT / "source" / "tests" / "test_e3_fit_v02.py"
    builder_source = Path(__file__).resolve()
    contract = copy.deepcopy(old_contract)
    contract["contract_id"] = "FAS_FROZEN_OBSERVER_BUNDLE_E3_FIT_V02"
    contract["status"] = "E3_V02_FIT_ONLY_FROZEN_BOUND_TO_V02_AUTHORIZATION"
    contract["created_utc"] = datetime.now(timezone.utc).isoformat()
    contract["predecessors"]["e3_v01_resource_disposition_sha256"] = disposition_hash
    contract["fit_outputs"]["root"] = str(E3_V02)
    contract["fit_outputs"]["bundle_id"] = "FAS_FROZEN_CAPABILITY_FABRIC_LFM12B_E3_V02"
    contract["output_root"] = str(E3_V02)
    contract["resources"]["disk_gate"] = {
        "required_before_output_creation": True,
        "measurement": "Python shutil.disk_usage on output-parent filesystem",
        "minimum_free_bytes": contract["resources"]["minimum_free_disk_bytes"],
        "record_pre_fit_and_post_fit_free_bytes": True,
    }
    contract["authorization_source"]["additional_user_instruction_quote"] = USER_CONTINUATION
    contract["authorization_source"]["additional_user_instruction_sha256"] = hashlib.sha256(
        USER_CONTINUATION.encode("utf-8")
    ).hexdigest()
    contract["implementation"] = {
        "fit_source_path": fit_source.relative_to(REPO_ROOT).as_posix(),
        "fit_source_sha256": sha256_file(fit_source)[0],
        "test_source_path": test_source.relative_to(REPO_ROOT).as_posix(),
        "test_source_sha256": sha256_file(test_source)[0],
        "builder_source_path": builder_source.relative_to(REPO_ROOT).as_posix(),
        "builder_source_sha256": sha256_file(builder_source)[0],
    }
    contract_bytes = write_json(contract_path, contract)
    contract_hash = hashlib.sha256(contract_bytes).hexdigest()

    authorization = {
        "authorization_id": "FAS_FROZEN_OBSERVER_BUNDLE_E3_FIT_AUTHORIZATION_V02",
        "project_id": "fas-frozen-observer-bundle-engineering-v01",
        "authorization_source": "continuation of the explicit user instruction to proceed to fitting, with a versioned engineering repair for an unmeasured frozen disk gate",
        "user_instruction_quote": USER_FIT_INSTRUCTION,
        "user_instruction_sha256": hashlib.sha256(USER_FIT_INSTRUCTION.encode("utf-8")).hexdigest(),
        "continuation_quote": USER_CONTINUATION,
        "continuation_sha256": hashlib.sha256(USER_CONTINUATION.encode("utf-8")).hexdigest(),
        "contract_path": str(contract_path.resolve()),
        "contract_sha256": contract_hash,
        "e0_root_sha256": EXPECTED_E0_ROOT,
        "e1_root_sha256": EXPECTED_E1_ROOT,
        "e2_root_sha256": EXPECTED_E2_ROOT,
        "fit_labels_sha256": contract["inputs"]["fit_labels"]["sha256"],
        "feature_cache_sha256": contract["inputs"]["feature_cache"]["sha256"],
        "prior_e3_v01_disposition_sha256": disposition_hash,
        "e3_fit_authorized": True,
        "e3_scoring_authorized": False,
        "evaluation_labels_opened": False,
        "authorized_heads": list(contract["tasks"]),
        "hyperparameter_search_authorized": False,
        "model_updates_authorized": False,
        "E4_integration_authorized": False,
        "recorded_utc": datetime.now(timezone.utc).isoformat(),
    }
    write_json(authorization_path, authorization)
    print(json.dumps({
        "status": contract["status"],
        "contract_sha256": contract_hash,
        "authorization_sha256": sha256_file(authorization_path)[0],
        "v01_disposition_sha256": disposition_hash,
        "fit_source_sha256": contract["implementation"]["fit_source_sha256"],
        "test_source_sha256": contract["implementation"]["test_source_sha256"],
        "output_root": str(E3_V02),
        "evaluation_scoring_authorized": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
