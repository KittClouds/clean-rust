"""Independent receipt-shape and contract audit for Q10-DA2."""
from __future__ import annotations

import json
import math
import struct
import sys
from pathlib import Path


def f32(value):
    return struct.unpack("<f", struct.pack("<f", value))[0]


def bits(value):
    return struct.unpack("<I", struct.pack("<f", value))[0]


def from_bits(value):
    return struct.unpack("<f", struct.pack("<I", value))[0]


def nextafter32(value, upward):
    return from_bits(bits(value) + (1 if upward else -1))


def sequential(row, weights):
    value = from_bits(0x80000000)
    for coordinate in row:
        value = f32(value + weights[coordinate])
    return value


def metric(actual, target):
    errors = [a - b for a, b in zip(actual, target)]
    return {
        "mismatch_count": sum(bits(a) != bits(b) for a, b in zip(actual, target)),
        "squared_error": math.fsum(error * error for error in errors),
        "l2": math.sqrt(math.fsum(error * error for error in errors)),
    }


def norm(values):
    return math.sqrt(math.fsum(value * value for value in values))


def dot(left, right):
    return math.fsum(a * b for a, b in zip(left, right))


def step_value(value, step):
    for _ in range(abs(step)):
        value = nextafter32(value, step > 0)
    return value


def recompute(source_event, source_set, result):
    fixture = source_event["fixture"]
    rows = fixture["operator"]["rows"]
    weights = [from_bits(value) for value in fixture["initial_weight_bits"]]
    target_weights = [from_bits(value) for value in fixture["target_weight_bits"]]
    base = [from_bits(value) for value in fixture["snapshot_base_bits"]]
    axis = fixture["acquisition_axis"]
    selected = source_set["selected_coordinates"]
    assert set(map(int, result["selected_steps"])) == set(selected)
    for coordinate in selected:
        step = int(result["selected_steps"][str(coordinate)])
        assert step in {0, -1, 1, -2, 2, -4, 4, -8, 8, -16, 16}
        weights[coordinate] = step_value(weights[coordinate], step)
        assert bits(weights[coordinate]) - bits(0.0) >= 16
        assert bits(2.0) - bits(weights[coordinate]) >= 16
    actual_readout = [sequential(row, weights) for row in rows]
    target_readout = [from_bits(value) for value in fixture["target_readout_bits"]]
    actual_metric = metric(actual_readout, target_readout)
    assert actual_metric["mismatch_count"] == result["readout"]["mismatch_count"]
    assert abs(actual_metric["squared_error"] - result["readout"]["squared_error"]) <= 1e-24
    displacement = [value - initial for value, initial in zip(weights, base)]
    target_displacement = [value - initial for value, initial in zip(target_weights, base)]
    target_axis = dot(target_displacement, axis)
    final_axis = dot(displacement, axis)
    target_norm = norm(target_displacement)
    final_norm = norm(displacement)
    true_drive = [math.fsum(target_displacement[i] for i in row) for row in rows]
    final_drive = [math.fsum(displacement[i] for i in row) for row in rows]
    cue_error = norm([a - b for a, b in zip(final_drive, true_drive)])
    cue_scale = max(norm(true_drive), 1e-12)
    geometry = {
        "axis_normalized_error": abs(final_axis - target_axis) / max(abs(target_axis), 1e-12),
        "norm_normalized_error": abs(final_norm - target_norm) / max(target_norm, 1e-12),
        "cue_linear_normalized_error": cue_error / cue_scale,
    }
    for key, value in geometry.items():
        assert abs(value - result["geometry"][key]) <= 1e-12, (key, value, result["geometry"][key])
    expected_pass = (
        geometry["axis_normalized_error"] <= 2e-6
        and geometry["norm_normalized_error"] <= 2e-7
        and geometry["cue_linear_normalized_error"] <= 2e-6
    )
    assert result["status"] == ("DA2_GEOMETRY_PASS" if expected_pass else "DA2_SELECTOR_GEOMETRY_FAIL")


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: audit_q10_da2.py OUTPUT")
    root = Path(sys.argv[1])
    execution = json.loads((root / "execution.json").read_text())
    results = json.loads((root / "results.json").read_text())
    seal = json.loads((root.parent.parent / "PREEXECUTION.json").read_text())
    source = Path(seal["input_root"])
    assert execution["protocol"] == "Q10-DA2"
    assert execution["declared_events"] == 8
    assert execution["sets"] == 32
    assert execution["scientific_seed_bundles_used"] == 0
    assert execution["behavioral_inference"] is False
    assert execution["future_dh08b_authorized"] is False
    assert len(results) == 32
    source_events = {}
    for path in sorted(source.glob("seed*.json")):
        event = json.loads(path.read_text())
        source_events[path.name] = event
    assert len(source_events) == 8
    for result in results:
        assert result["status"] in {"DA2_GEOMETRY_PASS", "DA2_SELECTOR_GEOMETRY_FAIL"}
        assert result["coordinate_count"] > 0
        assert result["candidate_count_audited"] > 0
        assert result["max_coordinate_step"] <= 16
        assert result["geometry"]["axis_normalized_error"] >= 0.0
        assert result["geometry"]["norm_normalized_error"] >= 0.0
        assert result["geometry"]["cue_linear_normalized_error"] >= 0.0
        event = source_events[result["source_event"]]
        source_set = event["sets"][result["set_index"]]
        recompute(event, source_set, result)
    print(f"Q10-DA2 independent receipt audit passed: {len(results)} sets")
    print(f"geometry passes={execution['geometry_passes']} failures={execution['geometry_failures']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
