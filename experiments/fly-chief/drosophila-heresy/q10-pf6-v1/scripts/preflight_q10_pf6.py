"""Fail-closed preflight for the Q10-PF6 oversize beam protocol."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def walk_forbidden(value: Any, forbidden: set[str], location: str = "receipt") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            require(str(key).lower() not in forbidden, f"forbidden field {location}.{key}")
            walk_forbidden(nested, forbidden, f"{location}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            walk_forbidden(nested, forbidden, f"{location}[{index}]")


def validate_pf6_clarifications(contract: dict[str, Any]) -> None:
    search = contract["search"]
    require(search["maximum_rounds"] == 16, "PF6 maximum round drift")

    expected_score = "S_i=sum(e_j^2 for j in R_i intersect M_G)"
    ranking = search["coordinate_order"]
    require(ranking["primary_score"] == expected_score, "PF6 ranking score drift")
    require(
        ranking["sort_terms"]
        == [
            {"name": "S_i", "direction": "descending"},
            {"name": "raw_support_row_count", "direction": "descending"},
            {"name": "replayed_raw_prefix_count", "direction": "descending"},
            {"name": "coordinate_id", "direction": "ascending"},
        ],
        "PF6 coordinate ranking order drift",
    )
    require(search["coordinate_residual_authority"] == expected_score, "PF6 residual authority drift")

    require(search["complete_endpoint_after_each_round"] is True, "PF6 endpoint completeness drift")
    require(search["visited_coordinate_choice"] == "chosen_legal_prefix", "PF6 visited-coordinate choice drift")
    require(search["unvisited_coordinate_choice"] == "legal_0", "PF6 unvisited-coordinate choice drift")
    require(search["horizon_is_coordinate_selection_only"] is True, "PF6 horizon semantics drift")
    require(search["round_16_endpoint"] == "valid_complete_legal_endpoint", "PF6 horizon endpoint drift")
    require(search["round_16_max_baseline_departures"] == 16, "PF6 horizon coordinate cap drift")

    trajectory = search["trajectory_diagnostics"]
    require(trajectory["per_group"] is True, "PF6 trajectory scope drift")
    require(
        trajectory["rounds_inclusive"] == {"first": 0, "last": 16, "count": 17},
        "PF6 trajectory round range drift",
    )
    require(
        trajectory["fields"]
        == [
            "mismatch_count",
            "total_ulp_distance",
            "residual_l2",
            "max_residual",
            "geometry_debt",
            "active_coordinate_count",
            "selected_coordinate_ids",
            "unselected_coordinate_ids",
        ],
        "PF6 trajectory fields drift",
    )
    require(trajectory["diagnostics_do_not_alter_stopping_or_objective"] is True, "PF6 trajectory control drift")

    require(search["unselected_zero_label"] == "unselected_zero_by_horizon", "PF6 unselected label drift")
    require(
        search["unselected_coordinate_forbidden_labels"] == ["ineffective", "no-authority"],
        "PF6 unselected label exclusions drift",
    )
    bounded_failure = search["bounded_search_failure"]
    require(bounded_failure["status"] == "INCONCLUSIVE_BOUNDED_SEARCH", "PF6 bounded-failure status drift")
    require(bounded_failure["inconclusive"] is True, "PF6 bounded-failure certainty drift")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.protocol_root.resolve()
    contract = json.loads((root / "CONTRACT.json").read_text(encoding="utf-8"))
    require(contract["protocol"] == "Q10-PF6", "protocol identity mismatch")
    validate_pf6_clarifications(contract)
    require((root / "PLAN.md").is_file(), "PF6 PLAN.md is unreadable")
    require(digest(root / "PLAN.md") == contract["plan_sha256"], "PF6 PLAN hash drift")
    parent_root = root.parent / "q10-pf5-v1"
    runtime = contract["runtime"]
    require(
        digest(parent_root / "scripts/run_q10_pf5.py") == runtime["pf5_helper_sha256"],
        "PF6 imported PF5 helper hash drift",
    )
    require(runtime["measured_parent_runner_sha256_remains_distinct"] is True, "PF6 runtime identity conflation")
    audit_root = parent_root / "qualification/full-run-v3-audit"
    qualification_root = parent_root / "qualification/full-run-v3"
    execution_path = audit_root / "execution.json"
    results_path = audit_root / "results.json"
    qualification_execution_path = qualification_root / "execution.json"
    qualification_results_path = qualification_root / "results.json"
    require(digest(parent_root / "PLAN.md") == contract["parent"]["plan_sha256"], "PF5 PLAN hash drift")
    require(digest(parent_root / "CONTRACT.json") == contract["parent"]["contract_sha256"], "PF5 CONTRACT hash drift")
    require(digest(qualification_execution_path) == contract["parent"]["qualification_execution_sha256"], "PF5 execution hash drift")
    require(digest(qualification_results_path) == contract["parent"]["qualification_results_sha256"], "PF5 results hash drift")
    require(digest(execution_path) == contract["parent"]["audit_execution_sha256"], "PF5 audit execution hash drift")
    require(digest(results_path) == contract["parent"]["audit_results_sha256"], "PF5 audit results hash drift")
    execution = json.loads(execution_path.read_text(encoding="utf-8"))
    qualification_execution = json.loads(qualification_execution_path.read_text(encoding="utf-8"))
    results = json.loads(results_path.read_text(encoding="utf-8"))
    require(qualification_execution.get("runner_sha256") == contract["parent"]["runner_sha256"], "PF5 executed runner hash drift")
    require(execution["status"] == "Q10_PF5_FULL_RECEIPT_AUDIT_COMPLETE", "PF5 audit status drift")
    require(execution["primary_endpoints"] == 28, "PF5 endpoint count drift")
    require(execution["groups"] == 1596, "PF5 group count drift")
    require(execution["status_counts"] == {
        "BLOCKED_WITHIN_DECLARED_DOMAIN": 37,
        "OVERSIZE_UNTESTED": 1457,
        "PARTIAL_FEASIBILITY_FOUND": 102,
    }, "PF5 audited classification drift")
    require(len(results["endpoint_results"]) == 1596, "PF5 result group cardinality drift")
    forbidden = {str(item).lower() for item in contract["forbidden_fields"]}
    walk_forbidden(execution, forbidden, "parent.execution")
    walk_forbidden(results, forbidden, "parent.results")
    print("Q10-PF6 preflight passed: parent=Q10-PF5 audited groups=1596 oversize=1457")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
