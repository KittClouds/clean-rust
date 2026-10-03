"""Create descriptive, engineering-only Q10-PF6-S1 result artifacts."""
from __future__ import annotations

import hashlib
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXECUTION = ROOT / "qualification/execution/execution.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def objective_key(value: dict[str, Any]) -> tuple[Any, ...]:
    return (
        int(value["mismatch_count"]),
        int(value["total_ulp_distance"]),
        float(value["residual_l2"]),
        float(value["max_residual"]),
    )


def improved(before: dict[str, Any], after: dict[str, Any]) -> bool:
    return objective_key(after) < objective_key(before)


def first_improvement(result: dict[str, Any], field: str) -> int | None:
    baseline = result["baseline"]
    for point in result["trajectory"]:
        state = point.get(field)
        if state is not None and improved(baseline, state):
            return int(point["round"])
    return None


def trajectory_metrics(result: dict[str, Any]) -> dict[str, Any]:
    baseline = result["trajectory"][0]["residual_l2"]
    d12 = float(result["trajectory"][12]["descriptive_residual_improvement"])
    d16 = float(result["trajectory"][16]["descriptive_residual_improvement"])
    search_round = first_improvement(result, "best_search_state")
    valid_round = first_improvement(result, "best_final_gate_valid_state")
    return {
        "first_search_improvement_round": search_round,
        "first_valid_improvement_round": valid_round,
        "late_horizon_improvement": valid_round is not None and valid_round >= 13,
        "post_round8_improvement": valid_round is not None and valid_round > 8,
        "d12": d12,
        "d16": d16,
        "h_g": d16 - d12,
        "baseline_residual_l2": baseline,
        "final_search_residual_l2": result["best_search"]["residual_l2"],
        "final_valid_residual_l2": (
            result["best_valid"]["residual_l2"] if result["best_valid"] else None
        ),
        "active_nonzero_coordinate_count": result["active_nonzero_coordinate_count"],
        "nodes_replayed": result["nodes_replayed"],
        "rounds_completed": result["rounds_completed"],
    }


def main() -> int:
    execution = json.loads(EXECUTION.read_text(encoding="utf-8"))
    results = execution["results"]
    per_group = []
    for result in results:
        metrics = trajectory_metrics(result)
        per_group.append({
            "identity": result["identity"],
            "endpoint": result["identity"][:2],
            "stratum": result["stratum"],
            "status": result["status"],
            **metrics,
        })

    statuses = Counter(result["status"] for result in results)
    valid_statuses = {"EXACT_TARGET_REACHED", "PARTIAL_FEASIBILITY_FOUND"}
    valid = [item for item in per_group if item["status"] in valid_statuses]
    search_improved = [item for item in per_group if item["first_search_improvement_round"] is not None]
    valid_improved = [item for item in valid if item["first_valid_improvement_round"] is not None]
    late = [item for item in valid if item["late_horizon_improvement"]]
    post8 = [item for item in valid if item["post_round8_improvement"]]
    geometry_pressure = [
        item for item in per_group
        if item["first_search_improvement_round"] is not None
        and item["first_valid_improvement_round"] is None
    ]
    flat = [item for item in per_group if item["first_search_improvement_round"] is None]

    strata: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for item in per_group:
        strata[item["stratum"]][item["status"]] += 1

    h_values = [item["h_g"] for item in per_group]
    aggregate = {
        "protocol": "Q10-PF6-S1",
        "status": "ENGINEERING_ONLY_COMPLETE_NO_SCIENTIFIC_PROMOTION",
        "execution_sha256": digest(EXECUTION),
        "sample_sha256": digest(ROOT / "qualification/sample.json"),
        "preexecution_sha256": digest(ROOT / "qualification/PREEXECUTION.json"),
        "counts": {
            "groups": len(results),
            "status_counts": dict(sorted(statuses.items())),
            "valid_sampled_groups": len(valid),
            "search_improved_groups": len(search_improved),
            "valid_improved_groups": len(valid_improved),
            "exact_groups": statuses.get("EXACT_TARGET_REACHED", 0),
            "late_horizon_improvement_groups": len(late),
            "post_round8_improvement_groups": len(post8),
            "geometry_pressure_groups": len(geometry_pressure),
            "flat_groups": len(flat),
        },
        "fractions": {
            "valid_of_sample": len(valid) / len(results),
            "late_of_valid": len(late) / len(valid) if valid else 0.0,
            "post8_of_valid": len(post8) / len(valid) if valid else 0.0,
            "geometry_pressure_of_sample": len(geometry_pressure) / len(results),
            "flat_of_sample": len(flat) / len(results),
        },
        "trajectory": {
            "h_g_mean": statistics.fmean(h_values),
            "h_g_median": statistics.median(h_values),
            "h_g_min": min(h_values),
            "h_g_max": max(h_values),
            "d16_mean": statistics.fmean(item["d16"] for item in per_group),
            "d16_median": statistics.median(item["d16"] for item in per_group),
            "first_valid_improvement_rounds": Counter(
                str(item["first_valid_improvement_round"])
                for item in valid_improved
            ),
        },
        "strata": {key: dict(sorted(value.items())) for key, value in sorted(strata.items())},
        "decision": {
            "longer_horizon_gate": len(late) / len(valid) >= 0.25 if valid else False,
            "ranking_audit_gate": len(post8) / len(valid) < 0.10 if valid else False,
            "geometry_balancing_gate": len(geometry_pressure) / len(results) >= 0.20,
            "widespread_flat_gate": len(flat) > len(results) / 2 and not geometry_pressure,
            "scientific_bundle_authorized": False,
            "recommended_next_identity": (
                "Q10-PF7-RANKING-AUDIT"
                if valid and len(post8) / len(valid) < 0.10
                else "Q10-PF7-HORIZON-QUALIFICATION"
                if valid and len(late) / len(valid) >= 0.25
                else "Q10-PF7-DISTRIBUTED-SEARCH-DIAGNOSTIC"
            ),
        },
        "per_group": per_group,
    }
    (ROOT / "qualification/execution/aggregate.json").write_text(
        json.dumps(aggregate, indent=2) + "\n", encoding="utf-8"
    )
    status = {
        "protocol": "Q10-PF6-S1",
        "status": aggregate["status"],
        "execution_sha256": aggregate["execution_sha256"],
        "aggregate_sha256": digest(ROOT / "qualification/execution/aggregate.json"),
        "audit": {
            "structural": "Q10_PF6_S1_STRUCTURAL_AUDIT_COMPLETE",
            "independent_replay": "Q10_PF6_S1_INDEPENDENT_REPLAY_AUDIT_COMPLETE",
        },
        "decision": aggregate["decision"],
    }
    (ROOT / "STATUS.json").write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    result_lines = [
        "# Q10-PF6-S1 result",
        "",
        "This was an engineering-only qualification of the frozen PF6 beam across 84 preselected oversized groups. It did not open behavior, science, canonical repair, or DH08B.",
        "",
        f"Measured execution: `{aggregate['execution_sha256']}`.",
        f"Status counts: `{json.dumps(dict(sorted(statuses.items())), sort_keys=True)}`.",
        f"Valid sampled groups: {len(valid)}/84; exact target endpoints: {statuses.get('EXACT_TARGET_REACHED', 0)}.",
        f"Late-round valid improvements (rounds 13–16): {len(late)}/{len(valid)} valid groups.",
        f"Valid improvements first appearing after round 8: {len(post8)}/{len(valid)}.",
        f"Readout improvements rejected only by final geometry: {len(geometry_pressure)}/84.",
        f"Median H_G = D_16 − D_12: {statistics.median(h_values):.6g}.",
        "",
        "The result is bounded constructor evidence only. Partial feasibility is not full-domain feasibility, and no behavioral or biological claim is promoted.",
        "",
        f"Next engineering identity selected by the frozen branch logic: `{aggregate['decision']['recommended_next_identity']}`.",
    ]
    (ROOT / "RESULT.md").write_text("\n".join(result_lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": aggregate["status"], "counts": aggregate["counts"], "decision": aggregate["decision"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
