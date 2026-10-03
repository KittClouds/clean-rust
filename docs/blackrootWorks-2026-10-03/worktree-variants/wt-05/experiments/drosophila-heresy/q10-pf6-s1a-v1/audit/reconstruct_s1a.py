"""Receipt-semantic reconstruction for Q10-PF6-S1A.

This module never constructs a PF6 candidate and never reruns the search.  It
reads committed S1 trajectory fields plus the sealed topology receipts needed
to identify each group's physical support rows.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
S1_ROOT = REPO / "experiments/drosophila-heresy/q10-pf6-s1-v1"
PF5_ROOT = REPO / "experiments/drosophila-heresy/q10-pf5-v1"
RMT_ROOT = REPO / "experiments/drosophila-heresy/q10-rmt-v1/qualification/sample-9731-9732"
OUT_ROOT = ROOT / "qualification/audit"

SCORE_FIELDS = ("mismatch_count", "total_ulp_distance", "residual_l2", "max_residual")
FORBIDDEN = {
    "accuracy", "reward", "actions", "old_map_margin", "reversed_map_margin",
    "behavior", "behavioral_inference", "scientific_seed_id", "repair_applied",
    "repair_applied_to_canonical_model", "dh08b_authorized",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def score(value: dict[str, Any]) -> tuple[Any, ...]:
    result = (
        int(value["mismatch_count"]),
        int(value["total_ulp_distance"]),
        float(value["residual_l2"]),
        float(value["max_residual"]),
    )
    require(all(math.isfinite(float(item)) for item in result[2:]), "non-finite receipt score")
    return result


def score_fields(value: dict[str, Any]) -> dict[str, Any]:
    return {field: value[field] for field in SCORE_FIELDS}


def state_signature(value: dict[str, Any] | None) -> tuple[int, ...] | None:
    if value is None:
        return None
    return tuple(int(item) for item in value.get("prefix", []))


def walk_forbidden(value: Any, location: str = "receipt") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            require(str(key).lower() not in FORBIDDEN, f"forbidden field {location}.{key}")
            walk_forbidden(nested, f"{location}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            walk_forbidden(nested, f"{location}[{index}]")


def verify_bindings(contract: dict[str, Any]) -> dict[str, str]:
    checked: dict[str, str] = {}
    require(contract["plan_sha256"] == digest(ROOT / "PLAN.md"), "S1A plan hash drift")
    paths: list[tuple[str, Path, str]] = []
    parent = contract["parent"]
    paths.extend([
        ("parent.execution", S1_ROOT / "qualification/execution/execution.json", parent["execution_sha256"]),
        ("parent.sample", S1_ROOT / "qualification/sample.json", parent["sample_sha256"]),
        ("parent.preexecution", S1_ROOT / "qualification/PREEXECUTION.json", parent["preexecution_sha256"]),
    ])
    for label, item in contract["lineage_helpers"].items():
        paths.append((f"lineage.{label}", REPO / item["path"], item["sha256"]))
    topology = contract["support_topology"]
    paths.append(("support.pf5_audit_results", REPO / topology["pf5_audit_results"]["path"], topology["pf5_audit_results"]["sha256"]))
    paths.append(("support.pf5_contract", REPO / topology["pf5_contract"]["path"], topology["pf5_contract"]["sha256"]))
    for label, item in topology["rmt_receipts"].items():
        paths.append((f"support.rmt.{label}", REPO / item["path"], item["sha256"]))
    for label, path, expected in paths:
        require(path.is_file(), f"missing bound input {label}: {path}")
        actual = digest(path)
        require(actual == expected.upper(), f"hash drift for {label}: {actual} != {expected}")
        checked[label] = actual
    return checked


def current_streams(result: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any] | None], list[dict[str, Any]], list[dict[str, Any] | None]]:
    current: list[dict[str, Any]] = []
    valid_raw: list[dict[str, Any] | None] = []
    for point in result["trajectory"]:
        top = score_fields(point)
        search = point["best_search_state"]
        require(score(top) == score(search), f"current search cross-check drift: {result['identity']} round={point['round']}")
        current.append(top)
        valid_raw.append(point.get("best_final_gate_valid_state"))
    best_search: list[dict[str, Any]] = []
    best_valid: list[dict[str, Any] | None] = []
    running_search: dict[str, Any] | None = None
    running_valid: dict[str, Any] | None = None
    for item, valid in zip(current, valid_raw):
        if running_search is None or score(item) < score(running_search):
            running_search = item
        best_search.append(running_search)
        if valid is not None and (running_valid is None or score(valid) < score(running_valid)):
            running_valid = score_fields(valid)
        best_valid.append(running_valid)
    return current, best_valid, best_search, valid_raw


def exposed(result: dict[str, Any], round_index: int) -> bool:
    if round_index == 0:
        return True
    return (
        round_index <= int(result["rounds_completed"])
        and round_index <= int(result["coordinates_total"])
    )


def strict_events(stream: list[dict[str, Any] | None], baseline: dict[str, Any], result: dict[str, Any]) -> list[int]:
    previous = score(baseline)
    events: list[int] = []
    for round_index, item in enumerate(stream):
        if round_index == 0 or item is None or not exposed(result, round_index):
            continue
        current = score(item)
        if current < previous:
            events.append(round_index)
            previous = current
    return events


def first_unexposed_hit(stream: list[dict[str, Any] | None], baseline: dict[str, Any]) -> int | None:
    base = score(baseline)
    for round_index, item in enumerate(stream):
        if item is not None and score(item) < base:
            return round_index
    return None


def termination(result: dict[str, Any]) -> str:
    if bool(result.get("replay_budget_exhausted", False)):
        return "REPLAY_BUDGET"
    coordinates = int(result["coordinates_total"])
    completed = int(result["rounds_completed"])
    expected = min(coordinates, 16)
    if completed < expected:
        return "NO_EXPANSION"
    if coordinates <= 16:
        return "NATURAL_COORDINATE_END"
    return "HORIZON"


def load_support_maps(selected: set[tuple[str, int, int]]) -> tuple[
    dict[tuple[str, int, int], dict[str, Any]],
    dict[tuple[str, int, int], set[int]],
    dict[tuple[str, int, int], set[int]],
    dict[tuple[str, int, int], dict[str, Any]],
]:
    inventory = load_json(PF5_ROOT / "qualification/full-run-v3-audit/results.json")["group_inventory"]
    groups = {
        (item["source_event"], int(item["set_index"]), int(item["group_index"])): item
        for item in inventory
        if (item["source_event"], int(item["set_index"]), int(item["group_index"])) in selected
    }
    require(set(groups) == selected, "selected S1 group missing from bound PF5 inventory")
    support: dict[tuple[str, int, int], set[int]] = {}
    coordinate_rows: dict[tuple[str, int, int], set[int]] = {}
    selected_endpoints = {(item[0], item[1]) for item in selected}
    with (RMT_ROOT / "moves.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            move = json.loads(line)
            key = (move["endpoint"], int(move["set_index"]), int(move["coordinate"]))
            if key[:2] not in selected_endpoints:
                continue
            coordinate_rows.setdefault(key, set()).update(int(row) for row in move.get("raw_rows", []))
    for group_key, group in groups.items():
        rows: set[int] = set()
        for coordinate in group["coordinates"]:
            rows.update(coordinate_rows.get((group_key[0], group_key[1], int(coordinate)), set()))
        support[group_key] = rows
    row_records = {
        (item["endpoint"], int(item["set_index"]), int(item["row"])): item
        for item in load_json(RMT_ROOT / "rows.json")
    }
    return groups, {key: rows for key, rows in support.items()}, coordinate_rows, row_records


def reconstruct() -> dict[str, Any]:
    contract = load_json(ROOT / "CONTRACT.json")
    checked = verify_bindings(contract)
    execution = load_json(S1_ROOT / "qualification/execution/execution.json")
    sample = load_json(S1_ROOT / "qualification/sample.json")
    require(execution["protocol"] == "Q10-PF6-S1", "wrong parent protocol")
    require(len(execution["results"]) == 84, "S1 result count drift")
    expected_ids = {tuple(item["identity"]) for item in sample["selected_groups"]}
    observed_ids = {tuple(item["identity"]) for item in execution["results"]}
    require(observed_ids == expected_ids, "S1 selected identities drift")
    selected = {(str(identity[0]), int(identity[1]), int(identity[2])) for identity in observed_ids}
    groups, supports, coordinate_rows, row_records = load_support_maps(selected)
    per_group: list[dict[str, Any]] = []
    round_events_valid: Counter[int] = Counter()
    round_events_search: Counter[int] = Counter()
    exposure_counts: Counter[int] = Counter()
    old_first_valid: list[int] = []
    old_first_search: list[int] = []
    corrected_late_groups: set[tuple[Any, ...]] = set()
    corrected_post8_groups: set[tuple[Any, ...]] = set()
    for result in execution["results"]:
        walk_forbidden(result, f"group.{result['identity']}")
        identity = tuple(result["identity"])
        group_key = (str(identity[0]), int(identity[1]), int(identity[2]))
        current, best_valid, best_search, valid_raw = current_streams(result)
        baseline = result["baseline"]
        valid_events = strict_events(best_valid, baseline, result)
        search_events = strict_events(best_search, baseline, result)
        for round_index in valid_events:
            round_events_valid[round_index] += 1
        for round_index in search_events:
            round_events_search[round_index] += 1
        for round_index in range(1, 17):
            if exposed(result, round_index):
                exposure_counts[round_index] += 1
        first_valid = first_unexposed_hit(valid_raw, baseline)
        first_search = first_unexposed_hit(current, baseline)
        if first_valid is not None:
            old_first_valid.append(first_valid)
        if first_search is not None:
            old_first_search.append(first_search)
        if any(round_index > 8 for round_index in valid_events):
            corrected_post8_groups.add(identity)
        if any(round_index >= 13 for round_index in valid_events):
            corrected_late_groups.add(identity)
        final_valid = best_valid[-1]
        final_score_round = None
        final_prefix_round = None
        equal_score_prefixes: set[tuple[int, ...]] = set()
        if final_valid is not None:
            final_score = score(final_valid)
            for point, valid_item in zip(result["trajectory"], valid_raw):
                if valid_item is not None and score(valid_item) == final_score and final_score_round is None:
                    final_score_round = int(point["round"])
            for point, valid_item in zip(result["trajectory"], valid_raw):
                if valid_item is not None and score(valid_item) == final_score:
                    signature = state_signature(valid_item)
                    if signature is not None:
                        equal_score_prefixes.add(signature)
            final_prefix = state_signature(valid_raw[-1])
            for point, valid_item in zip(result["trajectory"], valid_raw):
                if state_signature(valid_item) == final_prefix:
                    final_prefix_round = int(point["round"])
                    break
        group = groups[group_key]
        declared = set(int(row) for row in result["rows"])
        support = set(supports[group_key])
        endpoint_key = (group_key[0], group_key[1])
        endpoint_mismatches = {
            row for (endpoint, set_index, row), record in row_records.items()
            if endpoint == endpoint_key[0] and set_index == endpoint_key[1]
        }
        declared_records = [row_records[(endpoint_key[0], endpoint_key[1], row)] for row in declared if (endpoint_key[0], endpoint_key[1], row) in row_records]
        eligible = len(declared_records)
        threshold_count = sum(1 for record in declared_records if record.get("k_star") is not None and int(record["k_star"]) > 1)
        edge_count = sum(
            len(coordinate_rows.get((endpoint_key[0], endpoint_key[1], int(coordinate)), set()))
            for coordinate in group["coordinates"]
        )
        per_group.append({
            "identity": list(identity),
            "status": result["status"],
            "coordinates_total": int(result["coordinates_total"]),
            "rounds_completed": int(result["rounds_completed"]),
            "termination": termination(result),
            "exposed_rounds": [round_index for round_index in range(17) if exposed(result, round_index)],
            "first_valid_improvement_round_historical": first_valid,
            "first_search_improvement_round_historical": first_search,
            "valid_strict_improvement_rounds_exposed": valid_events,
            "search_strict_improvement_rounds_exposed": search_events,
            "last_valid_improvement_round_exposed": max(valid_events) if valid_events else None,
            "final_best_valid_score_discovery_round": final_score_round,
            "final_best_valid_prefix_discovery_round": final_prefix_round,
            "equal_score_prefix_count": len(equal_score_prefixes),
            "equal_score_prefix_drift": len(equal_score_prefixes) > 1,
            "best_state_hash_semantics": "prefix_identity_only",
            "domains": {
                "D_declared_rows": sorted(declared),
                "P_physical_support_rows": sorted(support),
                "G_whole_endpoint_score_observable": True,
                "D_per_row_score_observable": False,
                "P_per_row_score_observable": False,
                "collateral_attribution_observable": False,
            },
            "support": {
                "declared_intersection_count": len(declared & support),
                "declared_outside_support_count": len(declared - support),
                "support_row_count": len(support),
                "global_mismatch_outside_support_count": len(endpoint_mismatches - support),
                "raw_edge_count": edge_count,
                "density": edge_count / (len(group["coordinates"]) * len(support)) if group["coordinates"] and support else None,
            },
            "metadata": {
                "bridge_count": None,
                "bridge_count_status": "UNAVAILABLE_NOT_PRESENT_IN_SEALED_PF5_GROUP_RECEIPT",
                "threshold_gated_fraction_declared": threshold_count / eligible if eligible else None,
                "threshold_eligible_declared_rows": eligible,
                "threshold_source": "RMT_rows_k_star" if eligible == len(declared) else "PARTIAL_ROW_COVERAGE",
            },
        })
    valid_events_aggregate = {str(round_index): round_events_valid[round_index] for round_index in range(1, 17)}
    search_events_aggregate = {str(round_index): round_events_search[round_index] for round_index in range(1, 17)}
    term_counts = Counter(item["termination"] for item in per_group)
    statuses = Counter(item["status"] for item in per_group)
    valid_statuses = {"EXACT_TARGET_REACHED", "PARTIAL_FEASIBILITY_FOUND"}
    valid_groups = [item for item in per_group if item["status"] in valid_statuses]
    old_late = sum(1 for item in valid_groups if item["first_valid_improvement_round_historical"] is not None and item["first_valid_improvement_round_historical"] >= 13)
    old_post8 = sum(1 for item in valid_groups if item["first_valid_improvement_round_historical"] is not None and item["first_valid_improvement_round_historical"] > 8)
    exposed9 = exposure_counts[9]
    exposed13 = exposure_counts[13]
    late_distinct = len(corrected_late_groups)
    post8_distinct = len(corrected_post8_groups)
    return {
        "protocol": "Q10-PF6-S1A",
        "status": "Q10_PF6_S1A_VALID__RECEIPT_SEMANTICS_RECONSTRUCTED",
        "source_of_truth": {
            "execution_sha256": checked["parent.execution"],
            "sample_sha256": checked["parent.sample"],
            "preexecution_sha256": checked["parent.preexecution"],
            "support_topology_bound": True,
        },
        "coverage": {
            "receipt_semantics_coverage": "COMPLETE",
            "numerical_replay_coverage": "PARTIAL",
            "historical_replay_scope": "ONE_RETAINED_CANDIDATE_PER_GROUP",
        },
        "counts": {
            "groups": len(per_group),
            "status_counts": dict(sorted(statuses.items())),
            "valid_groups": len(valid_groups),
            "exact_groups": statuses.get("EXACT_TARGET_REACHED", 0),
            "corrected_valid_late_groups": late_distinct,
            "corrected_valid_post8_groups": post8_distinct,
        },
        "original_vs_corrected": {
            "original_first_hit_late": {"count": old_late, "denominator": len(valid_groups), "historical_only": True},
            "original_first_hit_post8": {"count": old_post8, "denominator": len(valid_groups), "historical_only": True},
            "corrected_best_valid_late_exposed": {"count": late_distinct, "denominator": exposed13, "fraction": late_distinct / exposed13 if exposed13 else None},
            "corrected_best_valid_post8_exposed": {"count": post8_distinct, "denominator": exposed9, "fraction": post8_distinct / exposed9 if exposed9 else None},
        },
        "round_exposure": {str(round_index): exposure_counts[round_index] for round_index in range(1, 17)},
        "strict_improvement_events": {
            "best_valid_exposed": valid_events_aggregate,
            "best_search_exposed": search_events_aggregate,
        },
        "termination_counts": dict(sorted(term_counts.items())),
        "spatial_support_summary": {
            "groups_with_support": sum(1 for item in per_group if item["support"]["support_row_count"] > 0),
            "global_mismatch_outside_support_min": min(item["support"]["global_mismatch_outside_support_count"] for item in per_group),
            "global_mismatch_outside_support_max": max(item["support"]["global_mismatch_outside_support_count"] for item in per_group),
            "per_row_parity_available": False,
            "collateral_attribution_available": False,
        },
        "groups": per_group,
        "scope": {
            "rerun": False,
            "candidate_generation": False,
            "search": False,
            "scientific_bundle_count": 0,
            "behavioral_probe": False,
            "dh08b_authorized": False,
        },
    }


def write_outputs(result: dict[str, Any]) -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    (OUT_ROOT / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Q10-PF6-S1A result",
        "",
        "Receipt-semantic audit only; no PF6 search or candidate replay was run.",
        "",
        f"Status: `{result['status']}`.",
        f"Groups: {result['counts']['groups']}; status counts: `{json.dumps(result['counts']['status_counts'], sort_keys=True)}`.",
        f"Corrected valid late-round groups: {result['counts']['corrected_valid_late_groups']}/{result['original_vs_corrected']['corrected_best_valid_late_exposed']['denominator']} exposed.",
        f"Corrected valid post-round-8 groups: {result['counts']['corrected_valid_post8_groups']}/{result['original_vs_corrected']['corrected_best_valid_post8_exposed']['denominator']} exposed.",
        f"Termination: `{json.dumps(result['termination_counts'], sort_keys=True)}`.",
        "",
        "Receipt-semantic coverage is complete. Numerical replay coverage remains partial and covers one retained candidate per group.",
        "Physical support sets are reconstructed from bound PF5/RMT topology; per-row candidate parity and collateral attribution are unavailable from the S1 receipts.",
        "",
        "S1A authorizes no ranking, horizon, scientific, behavioral, or DH08B conclusion.",
    ]
    (OUT_ROOT / "RESULT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    result = reconstruct()
    write_outputs(result)
    print(json.dumps({
        "status": result["status"],
        "groups": result["counts"]["groups"],
        "corrected_late": result["counts"]["corrected_valid_late_groups"],
        "corrected_post8": result["counts"]["corrected_valid_post8_groups"],
        "termination_counts": result["termination_counts"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
