"""Q10-RMT: exact residual topology and local repair-authority audit."""
from __future__ import annotations

import hashlib
import json
import math
import struct
import sys
from collections import defaultdict
from pathlib import Path

STEPS = (1, -1, 2, -2, 4, -4, 8, -8, 16, -16)
RESERVE = 16
AUTHORITY_COLUMN_CAP = 256


def f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def bits(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


def from_bits(value: int) -> float:
    return struct.unpack("<f", struct.pack("<I", value))[0]


def nextafter32(value: float, upward: bool) -> float:
    return from_bits(bits(value) + (1 if upward else -1))


def step_value(value: float, step: int) -> float:
    for _ in range(abs(step)):
        value = nextafter32(value, step > 0)
    return value


def sequential(row: list[int], weights: list[float], replacement=None) -> float:
    value = from_bits(0x80000000)
    for coordinate in row:
        term = replacement[1] if replacement and coordinate == replacement[0] else weights[coordinate]
        value = f32(value + term)
    return value


def norm(values: list[float]) -> float:
    return math.sqrt(math.fsum(value * value for value in values))


def dot(left: list[float], right: list[float]) -> float:
    return math.fsum(a * b for a, b in zip(left, right))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def canonical_zero(raw: int) -> int:
    return 0x80000000 if (raw & 0x7FFFFFFF) == 0 else raw


def ordered_f32(raw: int) -> int:
    raw = canonical_zero(raw)
    magnitude = raw & 0x7FFFFFFF
    if raw & 0x80000000:
        return 0x80000000 - magnitude
    return 0x80000000 + raw


def ulp_distance(left: float, right: float) -> int:
    return abs(ordered_f32(bits(left)) - ordered_f32(bits(right)))


def metric(actual: list[float], target: list[float]) -> dict:
    errors = [a - b for a, b in zip(actual, target)]
    return {
        "mismatch_count": sum(bits(a) != bits(b) for a, b in zip(actual, target)),
        "l1": math.fsum(abs(error) for error in errors),
        "l2": norm(errors),
        "squared_error": math.fsum(error * error for error in errors),
        "max_abs_error": max((abs(error) for error in errors), default=0.0),
    }


def legal_value(value: float, step: int, reserve: int) -> float | None:
    raw = bits(value)
    for _ in range(abs(step)):
        if step < 0 and raw == 0:
            return None
        if step > 0 and raw >= 0x7F7FFFFF:
            return None
        raw += 1 if step > 0 else -1
    candidate = from_bits(raw)
    raw = bits(candidate)
    if not (0.0 < candidate < 2.0):
        return None
    if raw - bits(0.0) < reserve or bits(2.0) - raw < reserve:
        return None
    return candidate


def support_index(rows: list[list[int]], coordinates: int) -> list[list[int]]:
    support = [[] for _ in range(coordinates)]
    for row_index, row in enumerate(rows):
        for coordinate in set(row):
            support[coordinate].append(row_index)
    return support


def geometry_signature(
    coordinate: int,
    candidate: float,
    weights: list[float],
    base: list[float],
    axis: list[float],
    rows: list[list[int]],
) -> dict:
    delta = candidate - weights[coordinate]
    displacement = [value - initial for value, initial in zip(weights, base)]
    displacement[coordinate] += delta
    before_norm = norm([value - initial for value, initial in zip(weights, base)])
    after_norm = norm(displacement)
    linear = [delta * row.count(coordinate) for row in rows]
    return {
        "axis_delta": delta * axis[coordinate],
        "norm_delta": after_norm - before_norm,
        "linear_l2_delta": norm(linear),
        "linear_max_abs_delta": max((abs(value) for value in linear), default=0.0),
    }


def replay_qualification(rows, weights, baseline, support, candidates):
    checked = 0
    passed = 0
    for coordinate, step in candidates:
        candidate = legal_value(weights[coordinate], step, RESERVE)
        if candidate is None:
            continue
        full_weights = weights[:]
        full_weights[coordinate] = candidate
        full = [sequential(row, full_weights) for row in rows]
        local = baseline[:]
        for row in support[coordinate]:
            local[row] = sequential(rows[row], weights, (coordinate, candidate))
        checked += 1
        passed += int(all(bits(a) == bits(b) for a, b in zip(full, local)))
    return checked, passed


def projection_residual(columns: list[list[float]], target: list[float]) -> tuple[float, int]:
    if not columns or not target:
        return 1.0, 0
    basis: list[list[float]] = []
    for column in columns[:AUTHORITY_COLUMN_CAP]:
        vector = column[:]
        for q in basis:
            coefficient = math.fsum(a * b for a, b in zip(vector, q))
            for index, value in enumerate(q):
                vector[index] -= coefficient * value
        length = norm(vector)
        if length <= 1.0e-14:
            continue
        basis.append([value / length for value in vector])
        if len(basis) == len(target):
            break
    residual = target[:]
    for q in basis:
        coefficient = math.fsum(a * b for a, b in zip(target, q))
        for index, value in enumerate(q):
            residual[index] -= coefficient * value
    target_norm = norm(target)
    return (norm(residual) / target_norm if target_norm else 0.0), len(basis)


def component_capacity(component_rows, moves, row_errors, geometry_scale):
    row_index = {row: index for index, row in enumerate(component_rows)}
    columns = []
    augmented = []
    for move in moves:
        if len(columns) >= AUTHORITY_COLUMN_CAP:
            break
        effects = {item[0]: item[1] for item in move["row_effects"] if item[0] in row_index}
        if not effects:
            continue
        vector = [effects.get(row, 0.0) for row in component_rows]
        columns.append(vector)
        augmented.append(vector + [
            move["axis_delta"] / geometry_scale[0],
            move["norm_delta"] / geometry_scale[1],
            move["linear_l2_delta"] / geometry_scale[2],
        ])
    target = [row_errors[row] for row in component_rows]
    readout_residual, readout_rank = projection_residual(columns, target)
    augmented_target = target + [0.0, 0.0, 0.0]
    geometry_residual, augmented_rank = projection_residual(augmented, augmented_target)
    return {
        "columns_available": len(columns),
        "columns_considered": min(len(columns), AUTHORITY_COLUMN_CAP),
        "readout_projection_residual": readout_residual,
        "readout_projection_rank": readout_rank,
        "geometry_augmented_projection_residual": geometry_residual,
        "geometry_augmented_projection_rank": augmented_rank,
    }


def union_find(rows: list[int], helpful_by_coordinate: dict[int, set[int]]):
    parent = {row: row for row in rows}

    def find(value):
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left, right):
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for linked in helpful_by_coordinate.values():
        linked = list(linked)
        for row in linked[1:]:
            union(linked[0], row)
    groups = defaultdict(list)
    for row in rows:
        groups[find(row)].append(row)
    return list(groups.values())


def process_endpoint(event, da2_result, moves_writer):
    fixture = event["fixture"]
    rows = fixture["operator"]["rows"]
    coordinate_count = fixture["operator"]["coordinates"]
    initial = [from_bits(value) for value in fixture["initial_weight_bits"]]
    target_weights = [from_bits(value) for value in fixture["target_weight_bits"]]
    base = [from_bits(value) for value in fixture["snapshot_base_bits"]]
    axis = fixture["acquisition_axis"]
    permitted = fixture["permitted"]
    interior = set(fixture["interior_indices"])
    selected_steps = da2_result["selected_steps"]
    alternative = initial[:]
    for coordinate_text, step in selected_steps.items():
        coordinate = int(coordinate_text)
        alternative[coordinate] = step_value(alternative[coordinate], int(step))
    baseline = [sequential(row, alternative) for row in rows]
    target_readout = [sequential(row, target_weights) for row in rows]
    baseline_metric = metric(baseline, target_readout)
    mismatch_rows = [
        row for row, (actual, target) in enumerate(zip(baseline, target_readout))
        if bits(actual) != bits(target)
    ]
    baseline_ulp = {row: ulp_distance(baseline[row], target_readout[row]) for row in mismatch_rows}
    support = support_index(rows, coordinate_count)
    row_coordinates = {row: set() for row in mismatch_rows}
    for coordinate, supported_rows in enumerate(support):
        for row in supported_rows:
            if row in row_coordinates:
                row_coordinates[row].add(coordinate)
    row_stats = {
        row: {
            "endpoint": da2_result["source_event"],
            "set_index": da2_result["set_index"],
            "row": row,
            "baseline_bits": bits(baseline[row]),
            "target_bits": bits(target_readout[row]),
            "residual": baseline[row] - target_readout[row],
            "baseline_ulp_distance": baseline_ulp[row],
            "one_step_raw_coordinates": set(),
            "one_step_helpful_coordinates": set(),
            "all_raw_coordinates": set(),
            "all_helpful_coordinates": set(),
            "best_remaining_ulp": baseline_ulp[row],
            "best_coordinate": None,
            "best_step": None,
            "best_fraction_removed": 0.0,
            "k_star": None,
        }
        for row in mismatch_rows
    }
    move_data = []
    recorded_move_count = [0]

    def inspect_move(coordinate, step, stage):
        candidate = legal_value(alternative[coordinate], step, RESERVE)
        if candidate is None:
            return None
        signature = geometry_signature(coordinate, candidate, alternative, base, axis, rows)
        raw_rows = []
        helpful_rows = []
        worse_rows = []
        row_effects = []
        for row in support[coordinate]:
            actual = sequential(rows[row], alternative, (coordinate, candidate))
            if row not in row_stats:
                continue
            delta = actual - baseline[row]
            before = baseline_ulp[row]
            after = ulp_distance(actual, target_readout[row])
            if bits(actual) != bits(baseline[row]):
                raw_rows.append(row)
                row_stats[row]["all_raw_coordinates"].add(coordinate)
            if after < before:
                helpful_rows.append(row)
                row_stats[row]["all_helpful_coordinates"].add(coordinate)
            elif after > before:
                worse_rows.append(row)
            if bits(actual) != bits(baseline[row]):
                row_effects.append([row, delta, after])
            if stage == "one":
                if bits(actual) != bits(baseline[row]):
                    row_stats[row]["one_step_raw_coordinates"].add(coordinate)
                if after < before:
                    row_stats[row]["one_step_helpful_coordinates"].add(coordinate)
            if after < row_stats[row]["best_remaining_ulp"]:
                row_stats[row]["best_remaining_ulp"] = after
                row_stats[row]["best_coordinate"] = coordinate
                row_stats[row]["best_step"] = step
                row_stats[row]["best_fraction_removed"] = 1.0 - after / before
        move = {
            "coordinate": coordinate,
            "step": step,
            "stage": stage,
            "raw_rows": raw_rows,
            "helpful_rows": helpful_rows,
            "worse_rows": worse_rows,
            "row_effects": row_effects,
            **signature,
        }
        move_data.append(move)
        if raw_rows or helpful_rows or worse_rows:
            moves_writer.write(json.dumps({
                "endpoint": da2_result["source_event"],
                "set_index": da2_result["set_index"],
                **move,
            }) + "\n")
            recorded_move_count[0] += 1
        return move

    all_legal_coordinates = [
        coordinate for coordinate in sorted(interior)
        if permitted[coordinate]
        and support[coordinate]
        and (
            legal_value(alternative[coordinate], 1, RESERVE) is not None
            or legal_value(alternative[coordinate], -1, RESERVE) is not None
        )
    ]
    target_support_coordinates = {
        coordinate for row in mismatch_rows for coordinate in row_coordinates[row]
    }
    legal_coordinates = [
        coordinate for coordinate in all_legal_coordinates if coordinate in target_support_coordinates
    ]
    structurally_zero_coordinates = len(all_legal_coordinates) - len(legal_coordinates)
    replay_candidates = []
    for coordinate in legal_coordinates[:8] + legal_coordinates[-8:]:
        replay_candidates.extend([(coordinate, 1), (coordinate, -1), (coordinate, 16), (coordinate, -16)])
    replay_checked, replay_passed = replay_qualification(rows, alternative, baseline, support, replay_candidates)
    for coordinate in legal_coordinates:
        inspect_move(coordinate, 1, "one")
        inspect_move(coordinate, -1, "one")
    one_step_orphans = [row for row in mismatch_rows if not row_stats[row]["one_step_helpful_coordinates"]]
    one_step_fragile = [
        row for row in mismatch_rows if len(row_stats[row]["one_step_helpful_coordinates"]) == 1
    ]
    stage2_rows = set(one_step_orphans + one_step_fragile)
    stage2_coordinates = sorted({
        coordinate for row in stage2_rows for coordinate in row_coordinates[row]
        if coordinate in set(legal_coordinates)
    })
    for coordinate in stage2_coordinates:
        for step in (2, -2, 4, -4, 8, -8, 16, -16):
            inspect_move(coordinate, step, "multi")
    for row in mismatch_rows:
        helpful = row_stats[row]["all_helpful_coordinates"]
        if helpful:
            helpful_steps = [
                abs(move["step"])
                for move in move_data
                if row in move["helpful_rows"]
            ]
            row_stats[row]["k_star"] = min(helpful_steps)
        for key in ("one_step_raw_coordinates", "one_step_helpful_coordinates", "all_raw_coordinates", "all_helpful_coordinates"):
            row_stats[row][key] = len(row_stats[row][key])
        row_stats[row]["class_one_step"] = (
            "orphan" if row_stats[row]["one_step_helpful_coordinates"] == 0
            else "fragile" if row_stats[row]["one_step_helpful_coordinates"] == 1
            else "broad"
        )
        row_stats[row]["class_final"] = (
            "no_local_authority" if row_stats[row]["k_star"] is None
            else "immediate" if row_stats[row]["k_star"] == 1
            else "threshold_gated"
        )
    helpful_by_coordinate = defaultdict(set)
    raw_by_coordinate = defaultdict(set)
    for move in move_data:
        for row in move["helpful_rows"]:
            helpful_by_coordinate[move["coordinate"]].add(row)
        for row in move["raw_rows"]:
            raw_by_coordinate[move["coordinate"]].add(row)
    helpful_rows = sorted({row for rows_for_coordinate in helpful_by_coordinate.values() for row in rows_for_coordinate})
    components = union_find(helpful_rows, helpful_by_coordinate)
    row_errors = {row: baseline[row] - target_readout[row] for row in mismatch_rows}
    true_displacement = [value - initial_value for value, initial_value in zip(target_weights, base)]
    geometry_scale = (max(abs(dot(true_displacement, axis)), 1e-12), max(norm(true_displacement), 1e-12), max(norm([math.fsum(true_displacement[i] for i in row) for row in rows]), 1e-12))
    component_records = []
    component_by_row = {}
    for index, component_rows in enumerate(sorted(components, key=lambda group: min(group))):
        component_rows = sorted(component_rows)
        component_coordinates = sorted({
            coordinate
            for row in component_rows
            for coordinate in row_coordinates[row]
            if row in helpful_by_coordinate.get(coordinate, set())
        })
        # Capacity is a readout-authority diagnostic, so retain raw authority
        # even when a move does not improve this endpoint's residual.
        component_moves = [move for move in move_data if set(move["raw_rows"]) & set(component_rows)]
        degrees = [row_stats[row]["all_helpful_coordinates"] for row in component_rows]
        total_component_sq = math.fsum(row_errors[row] * row_errors[row] for row in component_rows)
        capacity = component_capacity(component_rows, component_moves, row_errors, geometry_scale)
        record = {
            "endpoint": da2_result["source_event"],
            "set_index": da2_result["set_index"],
            "component_index": index,
            "rows": component_rows,
            "coordinates": component_coordinates,
            "row_count": len(component_rows),
            "coordinate_count": len(component_coordinates),
            "component_l2": math.sqrt(total_component_sq),
            "component_error_share": total_component_sq / max(baseline_metric["squared_error"], 1e-300),
            "orphan_rows": sum(row_stats[row]["class_final"] == "no_local_authority" for row in component_rows),
            "minimum_authority_degree": min(degrees, default=0),
            "median_authority_degree": sorted(degrees)[len(degrees) // 2] if degrees else 0,
            "maximum_authority_degree": max(degrees, default=0),
            "cooperative_shared_move_count": 0,
            "conflicting_shared_move_count": 0,
            **capacity,
        }
        for move in component_moves:
            local_rows = [row for row in move["row_effects"] if row[0] in component_rows]
            helpful = set(move["helpful_rows"]) & set(component_rows)
            worse = set(move["worse_rows"]) & set(component_rows)
            if len(helpful) >= 2:
                record["cooperative_shared_move_count"] += 1
            if helpful and worse:
                record["conflicting_shared_move_count"] += 1
        for row in component_rows:
            component_by_row[row] = index
        component_records.append(record)
    component_rows = {row: component_by_row.get(row) for row in mismatch_rows}
    endpoint_id = f"{da2_result['source_event']}#set{da2_result['set_index']}"
    row_records = []
    for row in mismatch_rows:
        item = dict(row_stats[row])
        item["component_index"] = component_rows[row]
        row_records.append(item)
    for item in row_records:
        for key in ("one_step_raw_coordinates", "one_step_helpful_coordinates", "all_raw_coordinates", "all_helpful_coordinates"):
            assert isinstance(item[key], int)
    positives = sum(row_errors[row] > 0.0 for row in mismatch_rows)
    negatives = sum(row_errors[row] < 0.0 for row in mismatch_rows)
    ulps = [baseline_ulp[row] for row in mismatch_rows]
    # Largest support-disjoint subset of legal coordinates. This is only a
    # topology diagnostic: no candidate is applied to the endpoint.
    occupied_rows = set()
    safe_additive_greedy_count = 0
    for coordinate in legal_coordinates:
        coordinate_rows = set(row_coordinates.get(coordinate, ()))
        if not (coordinate_rows & occupied_rows):
            safe_additive_greedy_count += 1
            occupied_rows.update(coordinate_rows)
    endpoint_record = {
        "endpoint": endpoint_id,
        "source_event": da2_result["source_event"],
        "set_index": da2_result["set_index"],
        "status": "RMT_VALID_ENDPOINT",
        "total_rows": len(rows),
        "mismatch_count": len(mismatch_rows),
        "mismatch_fraction": len(mismatch_rows) / max(len(rows), 1),
        "l1_error": baseline_metric["l1"],
        "l2_error": baseline_metric["l2"],
        "max_abs_error": baseline_metric["max_abs_error"],
        "total_ulp_distance": sum(ulps),
        "median_mismatched_row_ulp": sorted(ulps)[len(ulps) // 2] if ulps else 0,
        "max_mismatched_row_ulp": max(ulps, default=0),
        "positive_residual_rows": positives,
        "negative_residual_rows": negatives,
        "legal_coordinate_count": len(legal_coordinates),
        "all_legal_coordinate_count": len(all_legal_coordinates),
        "structurally_zero_coordinate_count": structurally_zero_coordinates,
        "one_step_move_count": len(legal_coordinates) * 2,
        "stage_two_rows": len(stage2_rows),
        "stage_two_coordinate_count": len(stage2_coordinates),
        "move_count_recorded": len(move_data),
        "move_count_serialized": recorded_move_count[0],
        "one_step_orphan_rows": len(one_step_orphans),
        "one_step_fragile_rows": len(one_step_fragile),
        "final_no_local_authority_rows": sum(item["class_final"] == "no_local_authority" for item in row_records),
        "threshold_gated_rows": sum(item["class_final"] == "threshold_gated" for item in row_records),
        "immediate_rows": sum(item["class_final"] == "immediate" for item in row_records),
        "helpful_components": len(component_records),
        "largest_component_rows": max((record["row_count"] for record in component_records), default=0),
        "largest_component_error_share": max((record["component_error_share"] for record in component_records), default=0.0),
        "local_replay_checks": replay_checked,
        "local_replay_passes": replay_passed,
        "local_replay_bitwise_qualified": replay_checked == replay_passed,
        "rows": row_records,
        "components": component_records,
        "safe_additive_greedy_count": safe_additive_greedy_count,
    }
    return endpoint_record, row_records, component_records


def main() -> int:
    if len(sys.argv) not in (4, 6):
        raise SystemExit("usage: run_q10_rmt.py DA2_ROOT DA1_QUALIFICATION OUTPUT [START STOP]")
    da2_root = Path(sys.argv[1]).resolve()
    da1_root = Path(sys.argv[2]).resolve()
    output = Path(sys.argv[3]).resolve()
    shard_start = int(sys.argv[4]) if len(sys.argv) == 6 else 0
    shard_stop = int(sys.argv[5]) if len(sys.argv) == 6 else None
    root = Path(__file__).parents[1]
    seal = json.loads((root / "PREEXECUTION.json").read_text())
    assert seal["protocol"] == "Q10-RMT"
    assert seal["status"] == "FROZEN_PRE_EXECUTION"
    for entry in seal["source_manifest"]:
        assert digest(root / entry["path"]) == entry["sha256"]
    assert digest(da2_root / "qualification/sample-9731-9732/results.json") == seal["da2-results-sha256"]
    for path in sorted(da1_root.glob("seed*.json")):
        assert digest(path) == seal["input_sha256"][path.name]
    output.mkdir(parents=True, exist_ok=False)
    da2_results = json.loads((da2_root / "qualification/sample-9731-9732/results.json").read_text())
    valid_results_all = [result for result in da2_results if result["status"] == "DA2_GEOMETRY_PASS"]
    valid_results = valid_results_all[shard_start:shard_stop]
    excluded_results = [result for result in da2_results if result["status"] != "DA2_GEOMETRY_PASS"]
    events = {path.name: json.loads(path.read_text()) for path in sorted(da1_root.glob("seed*.json"))}
    moves_path = output / "moves.jsonl"
    endpoint_records = []
    row_records = []
    component_records = []
    with moves_path.open("w", encoding="utf-8", newline="\n") as moves_writer:
        for result in valid_results:
            endpoint, rows, components = process_endpoint(events[result["source_event"]], result, moves_writer)
            endpoint_records.append(endpoint)
            row_records.extend(rows)
            component_records.extend(components)
    endpoints_path = output / "endpoints.json"
    rows_path = output / "rows.json"
    components_path = output / "components.json"
    endpoints_path.write_text(json.dumps(endpoint_records, indent=2) + "\n")
    rows_path.write_text(json.dumps(row_records, indent=2) + "\n")
    components_path.write_text(json.dumps(component_records, indent=2) + "\n")
    (output / "excluded-noncontract.json").write_text(json.dumps(excluded_results, indent=2) + "\n")
    persistence = defaultdict(lambda: {"mismatch": 0, "available": 0})
    for endpoint in endpoint_records:
        for row in endpoint["rows"]:
            persistence[row["row"]]["mismatch"] += 1
        for row in range(endpoint["total_rows"]):
            persistence[row]["available"] += 1
    authority_summary = {
        "endpoint_count": len(endpoint_records),
        "excluded_noncontract_endpoints": len(excluded_results),
        "mismatch_rows_total": len(row_records),
        "one_step_orphan_rows": sum(row["class_one_step"] == "orphan" for row in row_records),
        "one_step_fragile_rows": sum(row["class_one_step"] == "fragile" for row in row_records),
        "immediate_rows": sum(row["class_final"] == "immediate" for row in row_records),
        "threshold_gated_rows": sum(row["class_final"] == "threshold_gated" for row in row_records),
        "no_local_authority_rows": sum(row["class_final"] == "no_local_authority" for row in row_records),
        "largest_component_rows": max((component["row_count"] for component in component_records), default=0),
        "largest_component_error_share": max((component["component_error_share"] for component in component_records), default=0.0),
        "row_persistence": [
            {"row": row, "mismatch_count": values["mismatch"], "endpoint_count": values["available"], "persistence": values["mismatch"] / max(values["available"], 1)}
            for row, values in sorted(persistence.items())
        ],
        "repair_applied": False,
    }
    (output / "authority-summary.json").write_text(json.dumps(authority_summary, indent=2) + "\n")
    execution = {
        "protocol": "Q10-RMT",
        "status": "Q10_RMT_VALID__TOPOLOGY_MAPPED",
        "declared_da2_endpoints": 32,
        "primary_valid_endpoints": len(endpoint_records),
        "primary_valid_endpoint_slice": [shard_start, shard_stop],
        "excluded_noncontract_endpoints": len(excluded_results),
        "mismatch_rows_mapped": len(row_records),
        "component_records": len(component_records),
        "repair_applied": False,
        "behavioral_inference": False,
        "scientific_seed_bundles_used": 0,
        "dh08b_authorized": False,
        "local_replay_checks": sum(endpoint["local_replay_checks"] for endpoint in endpoint_records),
        "local_replay_passes": sum(endpoint["local_replay_passes"] for endpoint in endpoint_records),
        "next_decision": "Choose the next correction architecture from the sealed residual topology; do not open DH08B.",
    }
    (output / "execution.json").write_text(json.dumps(execution, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
