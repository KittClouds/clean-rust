"""Count-only feasibility audit for the v0.8B selection × composition cells."""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


CELL_FIELDS = (
    "world_family",
    "split_family_bundle_id",
    "query_view_type",
    "candidate_cardinality_bin",
    "posterior_entropy_quintile",
    "gold_entropy_band",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_ids(path: Path) -> set[str]:
    ids: set[str] = set()
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            value = json.loads(line).get("group_id")
            if not isinstance(value, str) or not value or value in ids:
                raise ValueError(f"invalid or duplicate group ID at {path}:{line_number}")
            ids.add(value)
    return ids


def gold_entropy_band(value: float) -> str:
    if value < 0.20:
        return "very_low"
    if value < 0.55:
        return "low"
    if value < 0.95:
        return "medium"
    if value < 1.30:
        return "high"
    return "very_high"


def training_entropy_thresholds(group_records: Path, eval_ids: set[str]) -> list[float]:
    values: list[float] = []
    with group_records.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            if row["group_id"] not in eval_ids:
                values.append(float(row["posterior_entropy_nats"]))
    if not values:
        raise ValueError("eligible pool is empty")
    values.sort()
    return [values[min(len(values) - 1, (len(values) * q) // 5)] for q in range(1, 5)]


def capacity_assignment_bound(demand_histogram: Counter[int], capacities: list[int]) -> dict[str, Any]:
    demands = [value for value, count in demand_histogram.items() for _ in range(count)]
    demands.sort(reverse=True)
    capacities = sorted(capacities, reverse=True)
    deficits = [
        (index, demand, capacities[index] if index < len(capacities) else 0)
        for index, demand in enumerate(demands)
        if demand > (capacities[index] if index < len(capacities) else 0)
    ]
    return {
        "demand_signature_count": len(demands),
        "available_signature_count": len(capacities),
        "necessary_capacity_bound_pass": not deficits,
        "deficit_signature_count": len(deficits),
        "total_missing_occurrence_capacity": sum(demand - capacity for _, demand, capacity in deficits),
        "maximum_demand_multiplicity": max(demands, default=0),
        "maximum_available_multiplicity": max(capacities, default=0),
    }


def multiplicity_histogram(counts: Counter[str]) -> Counter[int]:
    return Counter(counts.values())


def histogram_json(histogram: Counter[int]) -> dict[str, int]:
    return {str(key): value for key, value in sorted(histogram.items())}


def tv_distance(left: Counter[str], right: Counter[str]) -> float:
    left_total = sum(left.values())
    right_total = sum(right.values())
    if not left_total or not right_total:
        return 0.0 if not left_total and not right_total else 1.0
    categories = set(left) | set(right)
    return 0.5 * sum(
        abs(left.get(key, 0) / left_total - right.get(key, 0) / right_total)
        for key in categories
    )


def new_profile() -> dict[str, Any]:
    return {
        "groups": 0,
        "cells": Counter(),
        "query_views": Counter(),
        "cardinality": Counter(),
        "bundles": Counter(),
        "entropy_bands": Counter(),
        "entropy_quintiles": Counter(),
        "world_families": Counter(),
        "topology": Counter(),
        "intervention_family": Counter(),
        "inputs": Counter(),
        "input_cells": defaultdict(Counter),
        "roots": Counter(),
    }


def increment_profile(profile: dict[str, Any], row: dict[str, Any], quintile: str, input_id: str) -> None:
    strata = row["strata"]
    band = gold_entropy_band(float(row["posterior_entropy_nats"]))
    world = str(strata["world_family"])
    bundle = str(row["split_family_bundle_id"])
    query = str(strata["query_view_type"])
    cardinality = str(strata["candidate_cardinality_bin"])
    cell = (world, bundle, query, cardinality, quintile, band)
    profile["groups"] += 1
    profile["cells"][cell] += 1
    profile["query_views"][query] += 1
    profile["cardinality"][cardinality] += 1
    profile["bundles"][bundle] += 1
    profile["entropy_bands"][band] += 1
    profile["entropy_quintiles"][quintile] += 1
    profile["world_families"][world] += 1
    profile["inputs"][input_id] += 1
    profile["input_cells"][input_id][cell] += 1
    profile["roots"][str(row["root_id"])] += 1
    for feature in row["coverage_features"].get("structural_coverage", []):
        if str(feature).startswith("topology:"):
            profile["topology"][str(feature).removeprefix("topology:")] += 1
    intervention = row["family_ids"].get("intervention_family")
    if intervention is not None:
        profile["intervention_family"][str(intervention)] += 1


def profile_summary(profile: dict[str, Any]) -> dict[str, Any]:
    input_hist = multiplicity_histogram(profile["inputs"])
    root_hist = multiplicity_histogram(profile["roots"])
    cell_inputs: dict[tuple[str, ...], Counter[str]] = defaultdict(Counter)
    for input_id, cell_counts in profile["input_cells"].items():
        for cell, count in cell_counts.items():
            cell_inputs[cell][input_id] = count
    cell_input_histograms = {
        json.dumps(cell, separators=(",", ":")): histogram_json(multiplicity_histogram(inputs))
        for cell, inputs in sorted(cell_inputs.items())
    }
    return {
        "group_count": profile["groups"],
        "unique_input_count": len(profile["inputs"]),
        "input_occurrence_histogram": histogram_json(input_hist),
        "input_occurrence_histogram_by_joint_cell": cell_input_histograms,
        "input_signatures_spanning_multiple_joint_cells": sum(
            len(cells) > 1 for cells in profile["input_cells"].values()
        ),
        "unique_root_count": len(profile["roots"]),
        "root_occurrence_histogram": histogram_json(root_hist),
        "joint_cell_count": len(profile["cells"]),
        "joint_cell_counts": {
            json.dumps(cell, separators=(",", ":")): count
            for cell, count in sorted(profile["cells"].items())
        },
        "query_view_counts": dict(sorted(profile["query_views"].items())),
        "candidate_cardinality_counts": dict(sorted(profile["cardinality"].items())),
        "family_bundle_counts": dict(sorted(profile["bundles"].items())),
        "gold_entropy_band_counts": dict(sorted(profile["entropy_bands"].items())),
        "posterior_entropy_quintile_counts": dict(sorted(profile["entropy_quintiles"].items())),
        "world_family_counts": dict(sorted(profile["world_families"].items())),
        "topology_counts": dict(sorted(profile["topology"].items())),
        "intervention_family_counts": dict(sorted(profile["intervention_family"].items())),
    }


def run_audit(group_records: Path, r100_path: Path, c100_path: Path, eval_path: Path) -> dict[str, Any]:
    contract_path = Path(__file__).with_name("v08b-contract.json")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    r_ids = read_ids(r100_path)
    c_ids = read_ids(c100_path)
    eval_ids = read_ids(eval_path)
    if r_ids & eval_ids or c_ids & eval_ids:
        raise ValueError("existing training selector contains a NewTight-Eval group")
    thresholds = training_entropy_thresholds(group_records, eval_ids)
    targets = {"R100": new_profile(), "C100": new_profile()}
    found = {"R100": 0, "C100": 0}
    pool_cells: Counter[tuple[str, ...]] = Counter()
    pool_inputs: Counter[str] = Counter()
    pool_input_cells: dict[tuple[str, ...], Counter[str]] = defaultdict(Counter)
    pool_input_cell_sets: dict[str, set[tuple[str, ...]]] = defaultdict(set)
    pool_roots: Counter[str] = Counter()
    pool_count = 0
    eval_count = 0

    with group_records.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            group_id = str(row["group_id"])
            if group_id in eval_ids:
                eval_count += 1
                continue
            strata = row["strata"]
            value = float(row["posterior_entropy_nats"])
            quintile = f"q{bisect.bisect_right(thresholds, value) + 1}"
            input_keys = [
                str(key).removeprefix("model_input:")
                for key in row["overlap_keys"]
                if str(key).startswith("model_input:")
            ]
            if len(input_keys) != 1:
                raise ValueError(f"group needs one model_input digest at line {line_number}")
            input_id = input_keys[0]
            cell = (
                str(strata["world_family"]),
                str(row["split_family_bundle_id"]),
                str(strata["query_view_type"]),
                str(strata["candidate_cardinality_bin"]),
                quintile,
                gold_entropy_band(value),
            )
            pool_count += 1
            pool_cells[cell] += 1
            pool_inputs[input_id] += 1
            pool_input_cells[cell][input_id] += 1
            pool_input_cell_sets[input_id].add(cell)
            pool_roots[str(row["root_id"])] += 1
            for name, ids in (("R100", r_ids), ("C100", c_ids)):
                if group_id in ids:
                    increment_profile(targets[name], row, quintile, input_id)
                    found[name] += 1

    if found["R100"] != len(r_ids) or found["C100"] != len(c_ids) or eval_count != len(eval_ids):
        raise ValueError(
            "manifest membership mismatch: "
            f"R100 {found['R100']}/{len(r_ids)}, "
            f"C100 {found['C100']}/{len(c_ids)}, "
            f"eval {eval_count}/{len(eval_ids)}"
        )

    summaries = {name: profile_summary(profile) for name, profile in targets.items()}
    bounds: dict[str, Any] = {}
    for name, profile in targets.items():
        target_cells: Counter[tuple[str, ...]] = profile["cells"]
        unsupported = [
            (cell, need, pool_cells.get(cell, 0))
            for cell, need in target_cells.items()
            if need > pool_cells.get(cell, 0)
        ]
        input_bound = capacity_assignment_bound(multiplicity_histogram(profile["inputs"]), list(pool_inputs.values()))
        root_bound = capacity_assignment_bound(multiplicity_histogram(profile["roots"]), list(pool_roots.values()))
        cell_demands: dict[tuple[str, ...], Counter[str]] = defaultdict(Counter)
        for input_id, cell_counts in profile["input_cells"].items():
            for cell, count in cell_counts.items():
                cell_demands[cell][input_id] = count
        cell_input_bounds = {}
        for cell, demand_inputs in cell_demands.items():
            cell_input_bounds[json.dumps(cell, separators=(",", ":"))] = capacity_assignment_bound(
                multiplicity_histogram(demand_inputs),
                list(pool_input_cells.get(cell, Counter()).values()),
            )
        input_low = max(0, int(profile_summary(profile)["unique_input_count"] * 0.98))
        input_high = int(profile_summary(profile)["unique_input_count"] * 1.02 + 0.999999)
        root_count = len(profile["roots"])
        root_low = max(0, int(root_count * 0.98))
        root_high = int(root_count * 1.02 + 0.999999)
        bounds[name] = {
            "exact_joint_cell_capacity_pass": not unsupported,
            "unsupported_joint_cell_count": len(unsupported),
            "minimum_unused_groups_in_target_cells": min(
                (pool_cells.get(cell, 0) - need for cell, need in target_cells.items()),
                default=0,
            ),
            "unique_input_target_interval_2pct": [input_low, input_high],
            "eligible_unique_input_capacity": len(pool_inputs),
            "unique_root_target_interval_2pct": [root_low, root_high],
            "eligible_unique_root_capacity": len(pool_roots),
            "input_multiplicity_necessary_capacity_bound": input_bound,
            "joint_cell_input_multiplicity_capacity_bounds": cell_input_bounds,
            "joint_cell_input_bounds_all_pass": all(
                result["necessary_capacity_bound_pass"] for result in cell_input_bounds.values()
            ),
            "eligible_input_signatures_spanning_multiple_joint_cells": sum(
                len(cells) > 1 for cells in pool_input_cell_sets.values()
            ),
            "root_multiplicity_necessary_capacity_bound": root_bound,
            "warning": "Marginal capacity bounds are necessary, not a proof that simultaneous matching constraints are jointly feasible.",
        }

    return {
        "contract": "jev-decision-data-information-density/v0.8b-selection-composition-factorial",
        "status": "count_only_preflight_complete",
        "contract_sha256": sha256_file(contract_path),
        "preflight_source_sha256": sha256_file(Path(__file__)),
        "group_records_sha256": sha256_file(group_records),
        "r100_manifest_sha256": sha256_file(r100_path),
        "c100_manifest_sha256": sha256_file(c100_path),
        "eval_manifest_sha256": sha256_file(eval_path),
        "eligible_group_count": pool_count,
        "eval_group_count": eval_count,
        "training_entropy_quintile_thresholds_nats": thresholds,
        "manifest_membership": {
            "r100_expected": len(r_ids),
            "r100_found_in_eligible_pool": found["R100"],
            "c100_expected": len(c_ids),
            "c100_found_in_eligible_pool": found["C100"],
        },
        "reference_profiles": summaries,
        "eligible_capacity_bounds": bounds,
        "simultaneous_solver_feasibility": "not_yet_proven",
        "protected_text_or_model_outputs_read": False,
        "new_bank_ids_emitted": False,
        "model_contact_authorized": False,
        "phoenix_in_scope": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group-records", type=Path, required=True)
    parser.add_argument("--r100", type=Path, required=True)
    parser.add_argument("--c100", type=Path, required=True)
    parser.add_argument("--eval", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(f"refusing to overwrite preflight receipt: {args.out}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    report = run_audit(args.group_records, args.r100, args.c100, args.eval)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "new_bank_ids_emitted": False, "model_contact_authorized": False}))


if __name__ == "__main__":
    main()
