"""Qualification-only common runtime primitives for Q10-RH1-CQ1."""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
S1_ROOT = REPO / "experiments/drosophila-heresy/q10-pf6-s1-v1"
RMT_ROOT = REPO / "experiments/drosophila-heresy/q10-rmt-v1/qualification/sample-9731-9732"
OUT_ROOT = ROOT / "qualification"
AUTHORITY_STEPS = (1, -1, 2, -2, 4, -4, 8, -8, 16, -16)
SCORE_FIELDS = ("mismatch_count", "total_ulp_distance", "residual_l2", "max_residual")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def canonical_state(mapping: dict[int, int] | Iterable[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    pairs = tuple((int(coordinate), int(choice)) for coordinate, choice in dict(mapping).items()) if isinstance(mapping, dict) else tuple((int(coordinate), int(choice)) for coordinate, choice in mapping)
    result = tuple(sorted(pairs))
    require(len({coordinate for coordinate, _ in result}) == len(result), "duplicate coordinate in canonical state")
    return result


def canonical_bytes(mapping: dict[int, int] | Iterable[tuple[int, int]]) -> bytes:
    return json.dumps(canonical_state(mapping), separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def state_identity(mapping: dict[int, int] | Iterable[tuple[int, int]]) -> str:
    return hashlib.sha256(canonical_bytes(mapping)).hexdigest().upper()


def cache_key(context: tuple[Any, ...], mapping: dict[int, int] | Iterable[tuple[int, int]]) -> tuple[tuple[Any, ...], str]:
    return tuple(context), state_identity(mapping)


def strict_score(value: dict[str, Any]) -> tuple[Any, ...]:
    result = (
        int(value["mismatch_count"]),
        int(value["total_ulp_distance"]),
        float(value["residual_l2"]),
        float(value["max_residual"]),
    )
    require(all(math.isfinite(float(item)) for item in result[2:]), "non-finite strict score")
    return result


def _load_parent_bindings(contract: dict[str, Any]) -> dict[str, str]:
    preexecution = load_json(ROOT / "PREEXECUTION.json")
    require(preexecution["plan_sha256"] == digest(ROOT / "PLAN.md"), "RH1-CQ1 plan hash drift")
    require(preexecution["contract_sha256"] == digest(ROOT / "CONTRACT.json"), "RH1-CQ1 contract hash drift")
    checked: dict[str, str] = {}
    for binding in contract["provenance"]["parent_bindings"]:
        path = REPO / binding["path"]
        require(path.is_file(), f"missing parent binding: {binding['path']}")
        actual = digest(path)
        require(actual == binding["sha256"].upper(), f"parent hash drift: {binding['label']}")
        checked[binding["label"]] = actual
    rmt = contract["provenance"]["rmt_sample_root"]
    require(rmt.endswith("sample-9731-9732"), "unexpected RMT sample root")
    return checked


def load_groups() -> list[dict[str, Any]]:
    execution = load_json(S1_ROOT / "qualification/execution/execution.json")
    require(len(execution["results"]) == 84, "S1 group count drift")
    groups: list[dict[str, Any]] = []
    for result in execution["results"]:
        identity = result["identity"]
        groups.append({
            "identity": [identity[0], int(identity[1]), int(identity[2])],
            "endpoint": str(identity[0]),
            "set_index": int(identity[1]),
            "group_index": int(identity[2]),
            "coordinates": [int(value) for value in result["coordinates_ranked"]],
            "rows": [int(value) for value in result["rows"]],
            "coordinates_total": int(result["coordinates_total"]),
            "rounds_completed": int(result["rounds_completed"]),
        })
    return groups


def load_authority() -> tuple[dict[tuple[str, int, int], dict[str, Any]], int]:
    observations: dict[tuple[str, int, int], dict[str, Any]] = {}
    with (RMT_ROOT / "moves.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            move = json.loads(line)
            key = (str(move["endpoint"]), int(move["set_index"]), int(move["coordinate"]))
            item = observations.setdefault(key, {"steps": set(), "helpful_rows": set(), "helpful_steps": defaultdict(set), "raw_rows": set()})
            step = int(move["step"])
            item["steps"].add(step)
            item["raw_rows"].update(int(row) for row in move.get("raw_rows", []))
            for row in move.get("helpful_rows", []):
                row = int(row)
                item["helpful_rows"].add(row)
                item["helpful_steps"][row].add(step)
    return observations, len(observations)


def authority_tier(observation: dict[str, Any] | None) -> str:
    if observation is None:
        return "UNKNOWN"
    if set(observation["steps"]) == set(AUTHORITY_STEPS):
        return "MEASURED_COMPLETE"
    return "MEASURED_PARTIAL"


def authority_rank(group: dict[str, Any], observations: dict[tuple[str, int, int], dict[str, Any]], row_ulp: dict[tuple[str, int, int], int]) -> list[dict[str, Any]]:
    endpoint = group["endpoint"]
    set_index = group["set_index"]
    declared = set(group["rows"])
    row_ulp_for_group = {
        row: int(row_ulp.get((endpoint, set_index, row), 0))
        for row in declared
    }
    measured: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    for coordinate in group["coordinates"]:
        observation = observations.get((endpoint, set_index, coordinate))
        tier = authority_tier(observation)
        helpful_rows = (set(observation["helpful_rows"]) & declared) if observation else set()
        burden = sum(row_ulp_for_group.get(row, 0) for row in helpful_rows)
        min_step = min((abs(int(step)) for row in helpful_rows for step in observation["helpful_steps"][row]), default=None) if observation else None
        record = {
            "coordinate": coordinate,
            "coverage_tier": tier,
            "helpful_row_count": len(helpful_rows),
            "helpful_ulp_burden": burden,
            "minimum_helpful_prefix": min_step,
            "raw_support_mismatch_count": len((set(observation["raw_rows"]) if observation else set()) & declared),
        }
        (unknown if tier == "UNKNOWN" else measured).append(record)
    measured.sort(key=lambda item: (-item["helpful_row_count"], -item["helpful_ulp_burden"], item["minimum_helpful_prefix"] if item["minimum_helpful_prefix"] is not None else 10**9, -item["raw_support_mismatch_count"], item["coordinate"]))
    unknown.sort(key=lambda item: (-item["raw_support_mismatch_count"], item["coordinate"]))
    return measured + unknown


def residual_rank(group: dict[str, Any], residual_mass: dict[int, float], mismatched_rows: dict[int, int], replayed_prefix_count: dict[int, int]) -> list[dict[str, Any]]:
    records = [{
        "coordinate": coordinate,
        "residual_mass": float(residual_mass.get(coordinate, 0.0)),
        "mismatched_rows": int(mismatched_rows.get(coordinate, 0)),
        "replayed_prefix_count": int(replayed_prefix_count.get(coordinate, 0)),
    } for coordinate in group["coordinates"]]
    records.sort(key=lambda item: (-item["residual_mass"], -item["mismatched_rows"], -item["replayed_prefix_count"], item["coordinate"]))
    return records


def exposure(group: dict[str, Any], round_index: int) -> bool:
    return round_index == 0 or (round_index <= group["rounds_completed"] and round_index <= group["coordinates_total"])


def termination(group: dict[str, Any], budget_exhausted: bool = False) -> str:
    if budget_exhausted:
        return "REPLAY_BUDGET"
    if group["rounds_completed"] < min(group["coordinates_total"], 16):
        return "NO_EXPANSION"
    return "NATURAL_COORDINATE_END" if group["coordinates_total"] <= 16 else "HORIZON"


def qualify() -> dict[str, Any]:
    contract = load_json(ROOT / "CONTRACT.json")
    bindings = _load_parent_bindings(contract)
    groups = load_groups()
    observations, observation_count = load_authority()
    row_records = load_json(RMT_ROOT / "rows.json")
    row_ulp = {
        (item["endpoint"], int(item["set_index"]), int(item["row"])): int(item.get("baseline_ulp_distance", 0))
        for item in row_records
    }
    needed = {(group["endpoint"], group["set_index"], coordinate) for group in groups for coordinate in group["coordinates"]}
    present = needed & set(observations)
    coverage_fraction = len(present) / len(needed) if needed else 0.0
    require(coverage_fraction == 1.0, "authority endpoint-coordinate coverage gate failed")
    primary = [group for group in groups if group["coordinates_total"] >= 32]
    secondary = [group for group in groups if 17 <= group["coordinates_total"] <= 31]
    excluded = [group for group in groups if group not in primary and group not in secondary]
    require(len(primary) == 32, f"primary cohort drift: {len(primary)}")
    require(len(secondary) == 23, f"secondary cohort drift: {len(secondary)}")
    require(len(excluded) == 29, f"excluded cohort drift: {len(excluded)}")
    authority_rows = []
    authority_tiers = {"MEASURED_COMPLETE": 0, "MEASURED_PARTIAL": 0, "UNKNOWN": 0}
    for group in groups:
        ranked = authority_rank(group, observations, row_ulp)
        authority_rows.append({"identity": group["identity"], "ranked_coordinates": ranked})
        for item in ranked:
            authority_tiers[item["coverage_tier"]] += 1
    state_a = {91: 2, 17: -4, 43: 0}
    state_b = {43: 0, 91: 2, 17: -4}
    require(canonical_state(state_a) == canonical_state(state_b), "canonical state order is not permutation invariant")
    require(state_identity(state_a) == state_identity(state_b), "canonical identity drift")
    require(cache_key(("endpoint", 0, 7), state_a) == cache_key(("endpoint", 0, 7), state_b), "cache identity drift")
    return {
        "protocol": "Q10-PF6-RH1-CQ1",
        "status": "CQ1_SCAFFOLD_QUALIFIED_UNIT_SMOKE_ONLY",
        "measured_factorial_started": False,
        "parent_bindings_verified": bindings,
        "cohorts": {"primary": len(primary), "secondary": len(secondary), "excluded": len(excluded)},
        "authority": {
            "observed_endpoint_coordinate_pairs": len(present),
            "expected_endpoint_coordinate_pairs": len(needed),
            "coverage_fraction": coverage_fraction,
            "missing_is_unknown": True,
            "prefix_observation_tiers": authority_tiers,
            "observation_records": observation_count,
            "ranking": authority_rows,
        },
        "domains": {"D": "declared group rows", "P": "union of physical support rows", "G": "whole endpoint", "primary_search_domain": "D"},
        "exposure": {"rule": "actual_rounds_completed_and_coordinate_available", "termination_values": ["NATURAL_COORDINATE_END", "HORIZON", "REPLAY_BUDGET", "NO_EXPANSION", "INVALID"]},
        "budget": {"B16": 32768, "B32": 65536, "scaling": "B32_equals_2_times_B16"},
        "identity_audit": {"canonical_mapping": True, "ranking_position_excluded": True, "visitation_order_excluded": True, "na_information_used": False},
        "scope": {"scientific_seed_bundles": 0, "behavioral_probe": False, "rh1_f1_authorized": False},
    }


def write_report(result: dict[str, Any]) -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    (OUT_ROOT / "REPORT.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    text = [
        "# Q10-PF6-RH1-CQ1 report",
        "",
        "Qualification-only common-runtime and provenance check. No RH1 factorial execution ran.",
        "",
        f"Status: `{result['status']}`.",
        f"Cohorts: primary {result['cohorts']['primary']}, secondary {result['cohorts']['secondary']}, excluded {result['cohorts']['excluded']}.",
        f"Authority endpoint-coordinate coverage: {result['authority']['observed_endpoint_coordinate_pairs']}/{result['authority']['expected_endpoint_coordinate_pairs']}.",
        f"Prefix observation tiers: `{json.dumps(result['authority']['prefix_observation_tiers'], sort_keys=True)}`.",
        "Missing authority observations remain UNKNOWN and are never converted to zero.",
        "",
        "This report does not authorize RH1-F1, scientific seeds, behavior, or DH08B.",
    ]
    (OUT_ROOT / "REPORT.md").write_text("\n".join(text) + "\n", encoding="utf-8")
    (OUT_ROOT / "SMOKE_REPORT.json").write_text(json.dumps({"status": result["status"], "unit_smoke": "PASS", "factorial_started": False}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    result = qualify()
    write_report(result)
    print(json.dumps({"status": result["status"], "cohorts": result["cohorts"], "coverage": result["authority"]["coverage_fraction"]}, indent=2))
