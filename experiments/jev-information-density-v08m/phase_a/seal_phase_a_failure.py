"""Create the immutable local disposition for a non-promotable v0.8M Phase A."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "experiments/jev-information-density-v08m/phase_a/phase-a-v01-contract.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    run = Path(r"D:\codex-runs\jev-information-density-v08m\phase-a-v01-clean")
    selection = run / "selection"
    feature_cache = run / "feature-cache"
    exact = read_json(run / "phase-a0-independent-validation.json")
    selection_receipt = read_json(selection / "selection-receipt.json")
    feature_receipt = read_json(feature_cache / "extraction-receipt.json")
    radius = read_json(run / "phase-a1-radius-gate.json")
    generator_receipt = run / "generator-receipt.json"
    artifacts = {
        "contract": CONTRACT,
        "generator_receipt": generator_receipt,
        "exact_world_validation": run / "phase-a0-independent-validation.json",
        "selection_contract": selection / "selection-contract.json",
        "selection_manifest": selection / "selected-training-neighborhoods.jsonl",
        "selection_receipt": selection / "selection-receipt.json",
        "feature_authorization": feature_cache / "feature-extraction-authorization.json",
        "feature_scope": feature_cache / "training-feature-scope.jsonl",
        "feature_receipt": feature_cache / "extraction-receipt.json",
        "radius_gate": run / "phase-a1-radius-gate.json",
    }
    assert exact["status"] == "PHASE_A0_INDEPENDENT_EXACT_WORLD_VALIDATION_PASS"
    assert selection_receipt["status"] == "PHASE_A0_TRAINING_NEIGHBORHOOD_SELECTION_PASS"
    assert feature_receipt["status"] == "PHASE_A1_FEATURE_EXTRACTION_COMPLETE_TRAINING_ONLY"
    assert radius["status"] == "PHASE_A1_RADIUS_GATE_FAIL"
    receipt = {
        "status": "PHASE_A_NOT_PROMOTABLE_RADIUS_GATE_FAIL",
        "protocol": "jev-information-density/v0.8m-phase-a",
        "phase_a_identity": "phase-a-v01-clean",
        "contract_sha256": sha256_file(CONTRACT),
        "semantic_construction": "PASS",
        "independent_exact_world_validation": "PASS",
        "feature_extraction": "PASS_TRAINING_ONLY",
        "radius_gate": "FAIL",
        "failure_reason": {
            "mean_relative_radius_error": radius["overall"]["mean_relative_radius_error"],
            "mean_relative_radius_limit": radius["gate"]["mean_relative_radius_difference_max"],
            "p95_absolute_radius_error": radius["overall"]["p95_absolute_radius_error"],
            "p95_absolute_radius_limit": radius["gate"]["p95_absolute_radius_difference_max"],
            "maximum_family_mean_relative_error": max(item["mean_relative_radius_error"] for item in radius["families"].values()),
            "family_mean_relative_limit": radius["gate"]["per_family_mean_relative_difference_max"],
        },
        "replacement_selection_after_features": False,
        "threshold_relaxation": False,
        "luna_review": {
            "status": "LUNA_NO_ARTIFACT",
            "thread_id": "01a0c710-fd6b-7253-9dd2-72152ad3172a",
            "local_fallback_seal": True,
            "interpretation": "No independent Luna artifact was materialized; no Luna PASS is claimed.",
        },
        "phase_b_authorized": False,
        "model_head_training": False,
        "evaluation_inference": False,
        "protected_evaluation_bodies_opened": False,
        "newtight_access": False,
        "phoenix_access": False,
        "artifact_hashes": {name: sha256_file(path) for name, path in artifacts.items()},
    }
    out = run / "phase-a-failure-seal-final.json"
    out.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
