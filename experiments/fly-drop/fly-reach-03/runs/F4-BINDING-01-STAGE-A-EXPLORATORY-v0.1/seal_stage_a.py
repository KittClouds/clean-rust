"""Seal a compact terminal receipt from already locked Stage A artifacts."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
PARENT = ROOT.parent / "F4-PRESENTATION-03-EXECUTION-REPAIR-v0.1"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read(name: str) -> Any:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def q_pool(assignment_scores: dict[str, Any]) -> dict[str, Any]:
    parts = [assignment_scores[str(index)]["replicates"]["0"]["q_diagnostics"] for index in range(6)]
    count = sum(int(value["count"]) for value in parts)
    total = math.fsum(float(value["sum"]) for value in parts)
    squared = math.fsum(float(value["sum"]) ** 2 / float(value["ess"]) for value in parts)
    return {
        "count": count,
        "min": min(float(value["min"]) for value in parts),
        "max": max(float(value["max"]) for value in parts),
        "mean": total / count,
        "sum": total,
        "ess": total * total / squared,
        "ess_is_descriptive_only": True,
    }


def main() -> None:
    receipt_path = ROOT / "PRE-SCORING-INTEGRITY-RECEIPT.json"
    lock_path = ROOT / "STAGE-A-PREDICTION-LOCK.json"
    result_path = ROOT / "STAGE-A-ANALYSIS.json"
    analysis = read("STAGE-A-ANALYSIS.json")
    integrity = read("PRE-SCORING-INTEGRITY-RECEIPT.json")
    lock = read("STAGE-A-PREDICTION-LOCK.json")
    if integrity["status"] != "PASS" or integrity["prediction_lock_sha256"] != sha(lock_path):
        raise RuntimeError("Stage A integrity receipt does not bind the prediction lock")
    for item in lock["fit_outputs"]:
        if sha(ROOT / item["output_path"]) != item["output_sha256"]:
            raise RuntimeError(f"locked intervention output drift: {item['fit_id']}")
    artifacts = [
        "run_stage_a.py", "seal_stage_a.py", "STAGE-A-PREDICTION-LOCK.json", "PRE-SCORING-INTEGRITY-RECEIPT.json",
        "STAGE-A-ANALYSIS.json", "STAGE-A-RESULTS.md",
    ]
    pair = analysis["equal_weight_assignment_deltas"]["pair_swap"]
    cycle = analysis["equal_weight_assignment_deltas"]["cycle_4"]
    receipt = {
        "schema": "F4-BINDING-01-Stage-A-terminal-receipt-v0.1",
        "identity": "F4-BINDING-01-STAGE-A-EXPLORATORY-v0.1",
        "status": "EXPLORATORY_ANALYSIS_COMPLETE",
        "parent_identity": "F4-PRESENTATION-03-ENG1",
        "parent_terminal_sha256": sha(PARENT / "F4-PRESENTATION-03-TERMINAL-RECEIPT.json"),
        "parent_fit_manifest_sha256": sha(PARENT / "FIT-MANIFEST.csv"),
        "parent_prediction_lock_sha256": sha(PARENT / "PREDICTION-LOCK.json"),
        "parent_integrity_receipt_sha256": sha(PARENT / "INTEGRITY-RECEIPT.json"),
        "parent_analysis_sha256": sha(PARENT / "ANALYSIS.json"),
        "parent_truth_access_provenance": "Truth was previously opened in the parent lineage; this Stage A is exploratory and post-selection.",
        "frozen_cphi_models_used": 36,
        "fitting_or_predictions_rerun": False,
        "phi_recomputed": False,
        "intact_logits_bitwise_reproduced_for_all_models": True,
        "model_parameters_unchanged": True,
        "stored_phi_inputs_unchanged": True,
        "all_six_assignments_evaluable": pair["evaluable_assignment_count"] == 6,
        "assignment_order": pair["assignment_order"],
        "pair_swap_delta_balanced_error": pair["assignment_delta_error_vector"],
        "pair_swap_equal_assignment_mean_delta_error": pair["equal_weight_mean_delta_error"],
        "cycle_4_delta_balanced_error": cycle["assignment_delta_error_vector"],
        "cycle_4_equal_assignment_mean_delta_error": cycle["equal_weight_mean_delta_error"],
        "mean_balanced_error_across_assignment_replicate_cells": {
            condition: math.fsum(
                float(analysis["assignment_results"][str(assignment)]["replicates"][str(replicate)][condition]["balanced_error"])
                for assignment in range(6) for replicate in range(3)
            ) / 18.0
            for condition in ("intact", "pair_swap", "cycle_4")
        },
        "q_weight_diagnostics_pooled": q_pool(analysis["assignment_results"]),
        "assignment_specific_leverage_ess_and_top5_share": {
            analysis["assignment_results"][str(i)]["assignment_bits"]: {
                "leverage_ess_mean_over_replicates": math.fsum(float(analysis["assignment_results"][str(i)]["replicates"][str(r)]["intact"]["leverage_ess"]) for r in range(3)) / 3.0,
                "top_5pct_leverage_share": math.fsum(float(analysis["assignment_results"][str(i)]["replicates"][str(r)]["intact"]["top_5pct_share"]) for r in range(3)) / 3.0,
            }
            for i in range(6)
        },
        "stage_b_recommendation": "FRESH_PROSPECTIVE_CONFIRMATION_WARRANTED",
        "stage_b_execution_authorized": False,
        "scientific_or_biological_promotion": False,
        "measured_reach03_authorized": False,
        "pheno_status": "unchanged",
        "artifacts": {name: sha(ROOT / name) for name in artifacts},
        "intervention_output_count": len(lock["fit_outputs"]),
        "intervention_outputs_sha256": {
            item["fit_id"]: item["output_sha256"] for item in lock["fit_outputs"]
        },
    }
    path = ROOT / "STAGE-A-TERMINAL-RECEIPT.json"
    raw = (json.dumps(receipt, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"status": receipt["status"], "receipt_sha256": sha(path), "pair_swap_mean_delta": pair["equal_weight_mean_delta_error"], "cycle_mean_delta": cycle["equal_weight_mean_delta_error"]}, sort_keys=True))


if __name__ == "__main__":
    main()
