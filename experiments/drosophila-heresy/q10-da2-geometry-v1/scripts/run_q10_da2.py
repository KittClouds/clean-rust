"""Q10-DA2 qualification: geometry-constrained replay of sealed DA1 fixtures."""
from __future__ import annotations

import bisect
import hashlib
import json
import math
import struct
import sys
from pathlib import Path

STEPS = (0, -1, 1, -2, 2, -4, 4, -8, 8, -16, 16)
SEED_FILES = "seed*.json"


def f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def bits(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


def from_bits(value: int) -> float:
    return struct.unpack("<f", struct.pack("<I", value))[0]


def nextafter32(value: float, upward: bool) -> float:
    raw = bits(value)
    if (raw & 0x7F800000) == 0x7F800000:
        raise ValueError("non-finite f32 step")
    return from_bits(raw + (1 if upward else -1))


def sequential(row: list[int], weights: list[float], replacement=None) -> float:
    value = from_bits(0x80000000)
    for coordinate in row:
        term = replacement[1] if replacement and coordinate == replacement[0] else weights[coordinate]
        value = f32(value + term)
    return value


def metric(actual: list[float], target: list[float]) -> dict:
    errors = [a - b for a, b in zip(actual, target)]
    return {
        "mismatch_count": sum(bits(a) != bits(b) for a, b in zip(actual, target)),
        "squared_error": math.fsum(error * error for error in errors),
        "l2": math.sqrt(math.fsum(error * error for error in errors)),
    }


def norm(values: list[float]) -> float:
    return math.sqrt(math.fsum(value * value for value in values))


def dot(left: list[float], right: list[float]) -> float:
    return math.fsum(a * b for a, b in zip(left, right))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def legal_value(initial: float, step: int, reserve: int) -> float | None:
    value = initial
    for _ in range(abs(step)):
        value = nextafter32(value, step > 0)
    raw = bits(value)
    if not (0.0 < value < 2.0):
        return None
    if raw - bits(0.0) < reserve or bits(2.0) - raw < reserve:
        return None
    return value


def local_options(rows, support, weights, target, axis_value, coordinate, reserve):
    options = []
    for step in STEPS:
        value = legal_value(weights[coordinate], step, reserve)
        if value is None:
            continue
        local_rows = []
        squared = 0.0
        mismatches = 0
        for row in support:
            actual = sequential(rows[row], weights, (coordinate, value))
            error = actual - target[row]
            local_rows.append((row, actual))
            squared += error * error
            mismatches += bits(actual) != bits(target[row])
        options.append({
            "step": step,
            "value": value,
            "axis": (value - weights[coordinate]) * axis_value,
            "squared_error": squared,
            "mismatches": mismatches,
            "rows": local_rows,
        })
    return options


def choice_key(option):
    return (option["mismatches"], option["squared_error"], abs(option["step"]), option["step"])


def geometry_metrics(rows, weights, base, target_weights, axis, readout, target_readout):
    displacement = [value - initial for value, initial in zip(weights, base)]
    target_displacement = [value - initial for value, initial in zip(target_weights, base)]
    target_axis = dot(target_displacement, axis)
    final_axis = dot(displacement, axis)
    target_norm = norm(target_displacement)
    final_norm = norm(displacement)
    true_drive = [math.fsum(target_displacement[i] for i in row) for row in rows]
    final_drive = [math.fsum(displacement[i] for i in row) for row in rows]
    cue_error = norm([a - b for a, b in zip(final_drive, true_drive)])
    cue_scale = max(norm(true_drive), 1.0e-12)
    return {
        "axis_absolute_error": abs(final_axis - target_axis),
        "axis_normalized_error": abs(final_axis - target_axis) / max(abs(target_axis), 1.0e-12),
        "norm_absolute_error": abs(final_norm - target_norm),
        "norm_normalized_error": abs(final_norm - target_norm) / max(target_norm, 1.0e-12),
        "cue_linear_absolute_error": cue_error,
        "cue_linear_normalized_error": cue_error / cue_scale,
        "final_axis": final_axis,
        "target_axis": target_axis,
        "final_norm": final_norm,
        "target_norm": target_norm,
    }


def apply_choices(rows, initial_weights, initial_readout, choices):
    weights = initial_weights[:]
    readout = initial_readout[:]
    for coordinate, option in choices.items():
        weights[coordinate] = option["value"]
        for row, value in option["rows"]:
            readout[row] = value
    return weights, readout


def candidate_changes(coordinates, options, current):
    changes = []
    for coordinate in coordinates:
        selected = current[coordinate]
        for option in options[coordinate]:
            if option["step"] == selected["step"]:
                continue
            changes.append((
                option["axis"] - selected["axis"],
                option["squared_error"] - selected["squared_error"],
                option["mismatches"] - selected["mismatches"],
                coordinate,
                option,
            ))
    changes.sort(key=lambda item: item[0])
    return changes


def pair_candidates(changes, need, window):
    values = [item[0] for item in changes]
    candidates = [(abs(need), 0.0, 0, None, None)]
    for item in changes:
        candidates.append((abs(need - item[0]), item[1], item[2], item, None))
    for item in changes:
        index = bisect.bisect_left(values, need - item[0])
        lo = max(0, index - 4)
        hi = min(len(changes), index + 5)
        for other in changes[lo:hi]:
            if other[3] == item[3]:
                continue
            candidates.append((
                abs(need - item[0] - other[0]),
                item[1] + other[1],
                item[2] + other[2],
                item,
                other,
            ))
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    return candidates[:window]


def select_set(fixture, set_record, config):
    operator = fixture["operator"]
    rows = operator["rows"]
    initial_weights = [from_bits(value) for value in fixture["initial_weight_bits"]]
    target_weights = [from_bits(value) for value in fixture["target_weight_bits"]]
    base = [from_bits(value) for value in fixture["snapshot_base_bits"]]
    initial_readout = [from_bits(value) for value in fixture["initial_readout_bits"]]
    target_readout = [from_bits(value) for value in fixture["target_readout_bits"]]
    axis = fixture["acquisition_axis"]
    coordinates = set_record["selected_coordinates"]
    support = {coordinate: [] for coordinate in coordinates}
    for row_index, row in enumerate(rows):
        for coordinate in set(row):
            if coordinate in support:
                support[coordinate].append(row_index)
    options = {
        coordinate: local_options(
            rows,
            support[coordinate],
            initial_weights,
            target_readout,
            axis[coordinate],
            coordinate,
            config["minimum_final_reserve_ulps"],
        )
        for coordinate in coordinates
    }
    current = {coordinate: min(options[coordinate], key=choice_key) for coordinate in coordinates}
    target_displacement = [value - initial for value, initial in zip(target_weights, base)]
    initial_displacement = [value - initial for value, initial in zip(initial_weights, base)]
    axis_need = dot(target_displacement, axis) - dot(initial_displacement, axis)
    current_axis = math.fsum(option["axis"] for option in current.values())
    candidates = pair_candidates(
        candidate_changes(coordinates, options, current),
        axis_need - current_axis,
        config["pair_candidate_window"],
    )
    best = None
    best_any = None
    for candidate in candidates:
        chosen = current.copy()
        for change in (candidate[3], candidate[4]):
            if change is not None:
                chosen[change[3]] = change[4]
        final_weights, final_readout = apply_choices(rows, initial_weights, initial_readout, chosen)
        readout_metrics = metric(final_readout, target_readout)
        geometry = geometry_metrics(
            rows, final_weights, base, target_weights, axis, final_readout, target_readout
        )
        passes = (
            geometry["axis_normalized_error"] <= config["axis_normalized_tolerance"]
            and geometry["norm_normalized_error"] <= config["norm_normalized_tolerance"]
            and geometry["cue_linear_normalized_error"] <= config["cue_linear_normalized_tolerance"]
        )
        record = {
            "candidate_axis_residual": candidate[0],
            "selected_steps": {str(c): chosen[c]["step"] for c in coordinates},
            "selected_coordinates": [c for c in coordinates if chosen[c]["step"] != 0],
            "readout": readout_metrics,
            "geometry": geometry,
            "passes_geometry": passes,
            "sequential_bitwise_equal": all(
                bits(actual) == bits(target) for actual, target in zip(final_readout, target_readout)
            ),
            "max_coordinate_step": max(abs(option["step"]) for option in chosen.values()),
            "path_length": sum(option["step"] != 0 for option in chosen.values()),
        }
        rank = (
            0 if passes else 1,
            readout_metrics["mismatch_count"],
            readout_metrics["squared_error"],
            geometry["axis_normalized_error"],
            geometry["norm_normalized_error"],
        )
        if best_any is None or rank < best_any[0]:
            best_any = (rank, record)
        if passes and (best is None or rank < best[0]):
            best = (rank, record)
    chosen = best[1] if best else best_any[1]
    chosen["status"] = "DA2_GEOMETRY_PASS" if best else "DA2_SELECTOR_GEOMETRY_FAIL"
    chosen["candidate_count_audited"] = len(candidates)
    chosen["coordinate_count"] = len(coordinates)
    return chosen


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: run_q10_da2.py DA1_QUALIFICATION DA2_OUTPUT")
    source = Path(sys.argv[1]).resolve()
    output = Path(sys.argv[2]).resolve()
    root = Path(__file__).parents[1]
    seal = json.loads((root / "PREEXECUTION.json").read_text())
    assert seal["protocol"] == "Q10-DA2"
    assert seal["status"] == "FROZEN_PRE_EXECUTION"
    for entry in seal["source_manifest"]:
        assert sha256(root / entry["path"]) == entry["sha256"]
    for name, expected in seal["input_sha256"].items():
        assert sha256(source / name) == expected
    config = json.loads((root / "q10-da2-config.json").read_text())
    assert config["protocol"] == "Q10-DA2"
    assert config["scientific_seed_bundles"] == 0
    assert config["behavioral_inference"] is False
    assert config["dh08b_authorized"] is False
    output.mkdir(parents=True, exist_ok=False)
    results = []
    for path in sorted(source.glob(SEED_FILES)):
        event = json.loads(path.read_text())
        for set_record in event.get("sets", []):
            result = select_set(event["fixture"], set_record, config)
            result.update({
                "source_event": path.name,
                "set_index": set_record["set_index"],
                "selector_salt": set_record["selector_salt"],
            })
            results.append(result)
    passed = sum(result["status"] == "DA2_GEOMETRY_PASS" for result in results)
    summary = {
        "protocol": "Q10-DA2",
        "status": "ENGINEERING_COMPLETE",
        "source_sha256": {path.name: sha256(path) for path in sorted(source.glob(SEED_FILES))},
        "declared_events": len(list(source.glob(SEED_FILES))),
        "sets": len(results),
        "geometry_passes": passed,
        "geometry_failures": len(results) - passed,
        "scientific_seed_bundles_used": 0,
        "behavioral_inference": False,
        "future_dh08b_authorized": False,
        "readout_authority": "reported_from_committed_f32_replay",
        "next_decision": "Do not open DH08B; require a wider deterministic selector only if DA2 geometry qualification warrants it.",
    }
    (output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    (output / "execution.json").write_text(json.dumps(summary, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
