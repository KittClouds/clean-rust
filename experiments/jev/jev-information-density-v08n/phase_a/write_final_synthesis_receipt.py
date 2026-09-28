"""Write the final v0.8N synthesis receipt from the settled Road-B reconciliation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DOC = ROOT / "docs/jev-information-density-v0.8n-synthesis.md"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--eval-panel", type=Path, required=True)
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--execution-inputs", type=Path, required=True)
    args = parser.parse_args()
    road_a = args.run / "road-a"
    road_b = args.run / "road-b"
    a_seal = read_json(road_a / "seal/road-a-local-fallback-seal.json")
    reconciliation = read_json(road_b / "road-b-final-reconciliation-v2.json")
    seal = read_json(road_b / "seal-manifest.json")
    validation = read_json(road_b / "independent-validation.json")
    if a_seal["status"] != "V08N_ROAD_A_LOCAL_FALLBACK_SEAL_PASS":
        raise RuntimeError("Road-A seal not closed")
    if reconciliation["status"] != "V08N_ROAD_B_FINAL_RECONCILIATION_PASS" or reconciliation["current_hash_tree_mismatch_count"] != 0:
        raise RuntimeError("Road-B final reconciliation not clean")
    if seal["seal_status"] != "ROAD_B_SEALED_NOT_AUTHORIZED_FOR_PHASE_B" or seal["mismatch_count"] != 0:
        raise RuntimeError("Road-B current seal boundary/mismatch failure")
    if validation["status"] != "PASS":
        raise RuntimeError("Road-B validation failure")
    if sha256_file(road_b / "seal-manifest.json") != reconciliation["authoritative_current_seal_sha256"]:
        raise RuntimeError("Road-B current seal hash drift")
    if sha256_file(road_b / "branch-receipt.json") != reconciliation["current_branch_receipt_sha256"]:
        raise RuntimeError("Road-B current branch receipt hash drift")
    if sha256_file(road_b / "independent-validation.json") != reconciliation["current_independent_validation_sha256"]:
        raise RuntimeError("Road-B current validation hash drift")

    eval_panel = args.eval_panel
    eval_seal = read_json(eval_panel / "seal/seal-manifest.json")
    eval_validation = read_json(eval_panel / "seal/independent-validation.json")
    eval_firewall = read_json(eval_panel / "seal/evaluation-firewall-lock.json")
    eval_luna = read_json(eval_panel / "seal/luna-disposition.json")
    eval_radius = read_json(eval_panel / "matched-panel-v02/radius-gate-report.json")
    eval_axis = read_json(eval_panel / "matched-panel-v02/semantic-axis-composition.json")
    preflight = read_json(args.preflight)
    if eval_seal["status"] != "V08N_HELDOUT_MATCHED_PANEL_SEALED_PHASE_B_GATE_PASS":
        raise RuntimeError("held-out matched-neutral panel is not sealed")
    if eval_validation["status"] != "PASS":
        raise RuntimeError("held-out panel independent validation failure")
    if eval_firewall["status"] != "V08N_HELDOUT_PANEL_FIREWALL_LOCKED" or eval_firewall["body_access_granted"]:
        raise RuntimeError("held-out panel firewall is not locked")
    if not eval_seal["phase_b_ready"] or eval_seal["phase_b_authorized"]:
        raise RuntimeError("held-out panel authorization boundary drift")
    if eval_radius["status"] != "PASS" or not eval_radius["results"]["all_pass"]:
        raise RuntimeError("held-out panel radius gate failure")
    if preflight["status"] not in {"V08N_PHASE_B_PREFLIGHT_BLOCKED_PRIMARY_STREAM_UNRESOLVED", "V08N_PHASE_B_PREFLIGHT_PASS_READY_NOT_AUTHORIZED"}:
        raise RuntimeError("unexpected Phase-B preflight disposition")
    if preflight["phase_b_authorized"]:
        raise RuntimeError("Phase-B preflight authorization drift")
    execution_receipt = read_json(args.execution_inputs / "execution-inputs-receipt.json")
    execution_hash_tree = read_json(args.execution_inputs / "execution-inputs-hash-tree.json")
    if execution_receipt["status"] != "V08N_PHASE_B_INPUTS_MATERIALIZED_NO_MODEL_CONTACT":
        raise RuntimeError("execution-input materialization receipt is not clean")

    output = args.run / "synthesis" / "v08n-synthesis-receipt-final-v09.json"
    if output.exists():
        raise RuntimeError("refusing to overwrite final synthesis receipt")
    receipt = {
        "status": "V08N_SYNTHESIS_SEALED_CONSTRUCTION_ONLY",
        "phase_identity": "v0.8N-synthesis-v01-final",
        "road_a": {
            "identity": a_seal["phase_identity"],
            "seal_sha256": sha256_file(road_a / "seal/road-a-local-fallback-seal.json"),
            "atlas_sha256": next(v for k, v in a_seal["hash_tree"].items() if k.endswith("road-a-geometry-atlas.json")),
            "luna_disposition": a_seal["reviewer"]["luna_status"],
        },
        "road_b": {
            "identity": reconciliation["branch_identity"],
            "reconciliation_sha256": sha256_file(road_b / "road-b-final-reconciliation-v2.json"),
            "current_seal_sha256": reconciliation["authoritative_current_seal_sha256"],
            "current_branch_receipt_sha256": reconciliation["current_branch_receipt_sha256"],
            "current_validation_sha256": reconciliation["current_independent_validation_sha256"],
            "selected_control_sha256": reconciliation["current_selected_control_sha256"],
            "luna_disposition": reconciliation["luna_extra_high"]["status"],
        },
        "heldout_matched_neutral_panel": {
            "identity": eval_seal["identity"],
            "seal_sha256": sha256_file(eval_panel / "seal/seal-manifest.json"),
            "validation_sha256": sha256_file(eval_panel / "seal/independent-validation.json"),
            "hash_tree_sha256": sha256_file(eval_panel / "seal/heldout-panel-hash-tree.json"),
            "firewall_sha256": sha256_file(eval_panel / "seal/evaluation-firewall-lock.json"),
            "luna_disposition": eval_luna["status"],
            "radius_report_sha256": sha256_file(eval_panel / "matched-panel-v02/radius-gate-report.json"),
            "axis_report_sha256": sha256_file(eval_panel / "matched-panel-v02/semantic-axis-composition.json"),
            "neighborhood_count": eval_validation["neighborhood_count"],
            "mean_relative_radius_difference": eval_validation["mean_relative_radius_difference"],
            "p95_absolute_radius_difference": eval_validation["p95_absolute_radius_difference"],
            "per_family_mean_relative_radius_difference": eval_validation["per_family_mean_relative_radius_difference"],
            "semantic_axis_composition": eval_axis["axis_counts"],
            "phase_b_ready": True,
            "phase_b_authorized": False,
            "firewall_locked": True,
        },
        "phase_b_preflight": {
            "path": str(args.preflight),
            "sha256": sha256_file(args.preflight),
            "status": preflight["status"],
            "split_audit": preflight["split_audit"],
            "surface_audit": preflight["surface_audit"],
            "geometry_audit": preflight["geometry_audit"],
            "primary_stream_audit": preflight["primary_stream_audit"],
            "schedule_audit": preflight["schedule_audit"],
            "feature_space_audit": preflight["feature_space_audit"],
        },
        "phase_b_execution_inputs": {
            "root": str(args.execution_inputs),
            "receipt_sha256": sha256_file(args.execution_inputs / "execution-inputs-receipt.json"),
            "hash_tree_sha256": sha256_file(args.execution_inputs / "execution-inputs-hash-tree.json"),
            "common_primary_manifest_sha256": execution_receipt["common_primary_manifest"]["sha256"],
            "candidate_catalog_sha256": execution_receipt["candidate_catalog"]["sha256"],
            "fixed_training_schedule_sha256": execution_receipt["schedule"]["sha256"],
            "head_input_manifest_sha256": execution_receipt["head_input_manifests"],
            "candidate_tensor_deferred_until_authorized_phase_b": execution_receipt["candidate_catalog"]["feature_tensor_required_after_phase_b_authorization"],
            "contract_hash_bound_in_tree": execution_hash_tree["contract"],
        },
        "synthesis_document": {"path": str(DOC), "sha256": sha256_file(DOC)},
        "shared_feature_tensor_sha256": "da946af90353c91c3b1298d2951eebc42b9f515708b628d3a053e700a960c4d6",
        "model_head_training": False,
        "evaluation_inference": False,
        "protected_evaluation_bodies_opened": False,
        "phoenix_access": False,
        "phase_b_ready": preflight["status"] == "V08N_PHASE_B_PREFLIGHT_PASS_READY_NOT_AUTHORIZED",
        "phase_b_authorized": False,
        "promotable_for_training": False,
        "phase_b_blocking_reason": None if preflight["status"] == "V08N_PHASE_B_PREFLIGHT_PASS_READY_NOT_AUTHORIZED" else "Phase-B contract is not locked: common primary occurrence stream, exact auxiliary/interleaving schedule, and head-input feature materialization are unresolved.",
        "phase_b_preauthorization_gate": {
            "heldout_matched_neutral_panel_required": True,
            "heldout_families_and_templates_only": True,
            "exact_world_invariance_independently_validated": True,
            "neutral_generation_outcome_blind": True,
            "matching_rule": "frozen_radius_only",
            "direction_or_cosine_optimization": False,
            "training_head_contact": False,
            "replacement_selection_after_geometry_inspection": False,
            "panel_ids_and_hashes_frozen": True,
            "sham_matched_radius_gate_report_required": True,
            "semantic_axis_composition_report_required": True,
            "evaluation_firewall_sealed_before_training_or_evaluation": True,
        },
        "supersedes_non_authoritative_intermediate_receipt": "v08n-synthesis-receipt.json",
        "supersedes_receipt": "v08n-synthesis-receipt-final-v08.json",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
