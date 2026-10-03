"""Emit the metadata-only Phase 2C readiness and integrity receipts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUN = Path(r"D:\codex-runs\jev-information-density-v08c\phase2c-v01\cross-atom-search-v01")
SEARCH_CONTRACT = HERE / "v08c-phase2c-search-contract.json"
VALIDATION_CONTRACT = HERE / "v08c-phase2c-validation-v02-contract.json"
VALIDATION_RECEIPT = RUN / "validation-v02" / "freeze-receipt.json"
SEARCH_RECEIPT = RUN / "freeze-receipt.json"
SEARCH_REPORT = RUN / "rm100" / "search-report.json"
VALIDATION_REPORT = RUN / "validation-v02" / "rm100-candidate-validation.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_receipt(receipt: dict[str, Any]) -> None:
    for relative, expected in receipt.get("repository_sources", {}).items():
        if sha256_file(ROOT / relative) != expected:
            raise ValueError(f"frozen repository source changed: {relative}")
    for name, item in receipt.get("external_inputs", {}).items():
        if sha256_file(Path(item["path"])) != item["sha256"]:
            raise ValueError(f"frozen external input changed: {name}")


def write_new(path: Path, value: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(body)
    return sha256_file(path)


def main() -> int:
    for output in (RUN / "factorial-readiness.json", RUN / "phase2c-integrity-receipt.json"):
        if output.exists():
            raise FileExistsError(f"refusing to overwrite final Phase 2C artifact: {output}")

    search_contract = read_json(SEARCH_CONTRACT)
    validation_contract = read_json(VALIDATION_CONTRACT)
    search_receipt = read_json(SEARCH_RECEIPT)
    validation_receipt = read_json(VALIDATION_RECEIPT)
    search = read_json(SEARCH_REPORT)
    validation = read_json(VALIDATION_REPORT)
    verify_receipt(search_receipt)
    verify_receipt(validation_receipt)

    if search_receipt.get("status") != "SEALED_BEFORE_CROSS_ATOM_SEARCH":
        raise ValueError("search freeze is not sealed")
    if validation_receipt.get("status") != "SEALED_BEFORE_INDEPENDENT_VALIDATION_V02":
        raise ValueError("validation v02 freeze is not sealed")
    if search_receipt.get("contract_sha256") != sha256_file(SEARCH_CONTRACT):
        raise ValueError("search contract does not match its freeze receipt")
    if validation_receipt.get("contract_sha256") != sha256_file(VALIDATION_CONTRACT):
        raise ValueError("validation contract does not match its freeze receipt")
    if validation.get("source_hashes", {}).get("candidate_manifest") != sha256_file(
        Path(search["candidate_manifest"]["path"])
    ):
        raise ValueError("independent validation did not bind the candidate manifest")
    if validation.get("source_hashes", {}).get("search_report") != sha256_file(SEARCH_REPORT):
        raise ValueError("independent validation did not bind the search report")
    if search["distance"]["exact_training_signature_distance"] != validation["distance"]["exact_training_signature_distance"]:
        raise ValueError("search and independent training-signature distances disagree")

    minimum = float(search_contract["search"]["treatment"]["minimum_exact_training_signature_distance"])
    profile_pass = bool(validation["gate"]["profile_pass"])
    policy_pass = bool(validation["gate"]["policy_gain_pass"])
    distance = float(validation["distance"]["exact_training_signature_distance"])
    treatment_pass = distance >= minimum
    candidate_validated = validation.get("status") == "PASS_MODEL_COUNTERFACTUAL_AND_POLICY_SEPARATION"
    if candidate_validated != (profile_pass and policy_pass and treatment_pass):
        raise ValueError("independent validator status conflicts with its component gates")
    cm_was_run = (RUN / "cm100").exists()
    if cm_was_run:
        raise ValueError("CM100 exists although the frozen RM-first gate did not pass")

    readiness = {
        "protocol": "jev-decision-data-information-density/v0.8c-phase2c-factorial-readiness",
        "status": "FACTORIAL_NOT_READY_TREATMENT_TOO_WEAK" if not candidate_validated else "RM100_READY_CM100_NOT_RUN",
        "decision": {
            "RM100_independent_validation_pass": candidate_validated,
            "CM100_search_run": cm_was_run,
            "factorial_ready": False,
            "model_contact_authorized": False,
            "training_authorized": False,
            "phoenix_access": False,
            "reason": "RM100 profile and policy gates pass, but its exact learner-visible training-signature distance is below the frozen treatment threshold; CM100 remains conditional and was not run.",
        },
        "banks": {
            "RM100": {
                "search_status": search["status"],
                "stop_reason": search["search"]["stop_reason"],
                "candidate_groups": search["candidate_group_count"],
                "changed_raw_group_ids": search["start_to_candidate_changed_ids"],
                "accepted_unit_transfers": search["search"]["accepted_unit_transfers"],
                "objective_gain_vs_C100": validation["objective"]["gain_vs_reference"],
                "profile_pass": profile_pass,
                "exact_training_signature_distance": distance,
                "required_distance": minimum,
                "treatment_strength_pass": treatment_pass,
                "validation_status": validation["status"],
                "candidate_manifest_sha256": search["candidate_manifest"]["sha256"],
            },
            "CM100": {
                "status": "NOT_RUN_CONDITIONAL_RM100_GATE_FAILED",
                "start_candidate": search_contract["search"]["start_states"]["CM100"],
            },
        },
        "provenance": {
            "search_contract_sha256": sha256_file(SEARCH_CONTRACT),
            "search_freeze_receipt_sha256": sha256_file(SEARCH_RECEIPT),
            "search_report_sha256": sha256_file(SEARCH_REPORT),
            "validation_contract_sha256": sha256_file(VALIDATION_CONTRACT),
            "validation_freeze_receipt_sha256": sha256_file(VALIDATION_RECEIPT),
            "validation_report_sha256": sha256_file(VALIDATION_REPORT),
        },
    }
    readiness_path = RUN / "factorial-readiness.json"
    readiness_sha = write_new(readiness_path, readiness)
    integrity = {
        "protocol": "jev-decision-data-information-density/v0.8c-phase2c-integrity-receipt",
        "status": "SEALED_BOUNDED_SEARCH_OUTCOME",
        "artifact_sha256": {
            "factorial_readiness": readiness_sha,
            "search_contract": sha256_file(SEARCH_CONTRACT),
            "search_freeze_receipt": sha256_file(SEARCH_RECEIPT),
            "RM100_search_report": sha256_file(SEARCH_REPORT),
            "RM100_candidate_manifest": sha256_file(Path(search["candidate_manifest"]["path"])),
            "validation_v02_contract": sha256_file(VALIDATION_CONTRACT),
            "validation_v02_freeze_receipt": sha256_file(VALIDATION_RECEIPT),
            "RM100_independent_validation": sha256_file(VALIDATION_REPORT),
        },
        "scope": {
            "prior_banks_or_phases_mutated": False,
            "model_or_tokenizer_access": False,
            "feature_cache_access": False,
            "training_materialized": False,
            "phoenix_access": False,
            "CM100_run": False,
            "candidate_is_finalized_or_promoted": False,
            "RM100_is_globally_optimal": False,
        },
        "execution_note": "The first validator invocation halted on a dict-versus-set Eval-membership type error before writing a result. A separately frozen v02 wrapper corrected only that type conversion and reran the unchanged raw-record validation logic.",
    }
    integrity_path = RUN / "phase2c-integrity-receipt.json"
    integrity_sha = write_new(integrity_path, integrity)
    print(json.dumps({
        "readiness": readiness["status"],
        "D_train": distance,
        "required_D_train": minimum,
        "factorial_readiness_sha256": readiness_sha,
        "integrity_receipt_sha256": integrity_sha,
        "factorial_readiness_path": str(readiness_path),
        "integrity_receipt_path": str(integrity_path),
    }, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
