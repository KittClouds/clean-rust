"""Minimal deterministic PF5 dry run.

This is an engineering-only slice.  It reconstructs one sealed Q10-RMT
endpoint, derives raw-support legal coordinates, and replays a few complete
prefix domains on cloned binary32 weights.  It never mutates a canonical
endpoint and never opens behavior or repair.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from qualify_q10_pf5 import (
    CHOICES,
    QualificationError,
    audit_parent,
    bits,
    f32,
    from_bits,
    nextafter32,
    prefix_value,
)


RESERVE_ULPS = 16
SOURCE_EVENT = "seed9731-L-tau16.json"
SET_INDEX = 0


def sequential(row: list[int], weights: list[float]) -> float:
    value = from_bits(0x8000_0000)
    for coordinate in row:
        value = f32(value + weights[coordinate])
    return value


def sequential_readout(rows: list[list[int]], weights: list[float]) -> list[float]:
    return [sequential(row, weights) for row in rows]


def legal_value(value: float, choice: int) -> float | None:
    if choice == 0:
        return value
    candidate = prefix_value(value, choice)
    raw = bits(candidate)
    if not (0.0 < candidate < 2.0):
        return None
    if raw - bits(0.0) < RESERVE_ULPS:
        return None
    if bits(2.0) - raw < RESERVE_ULPS:
        return None
    return candidate


def prefix_domain(value: float) -> list[int]:
    return [choice for choice in CHOICES if legal_value(value, choice) is not None]


def load_event(repo_root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    source = (
        repo_root
        / "experiments/drosophila-heresy/q10-distributed-additive-v1/qualification/sample-9731-9732"
        / SOURCE_EVENT
    )
    da2_path = (
        repo_root
        / "experiments/drosophila-heresy/q10-da2-geometry-v1/qualification/sample-9731-9732/results.json"
    )
    event = json.loads(source.read_text(encoding="utf-8"))
    da2 = json.loads(da2_path.read_text(encoding="utf-8"))
    result = next(
        item
        for item in da2
        if item["source_event"] == SOURCE_EVENT and item["set_index"] == SET_INDEX
    )
    if result["status"] != "DA2_GEOMETRY_PASS":
        raise QualificationError("dry-run source endpoint is not a DA2 geometry pass")
    endpoint = event["sets"][SET_INDEX]
    return event, endpoint, result


def reconstruct_weights(fixture: dict[str, Any], selected_steps: dict[str, int]) -> list[float]:
    weights = [from_bits(raw) for raw in fixture["initial_weight_bits"]]
    for coordinate_text, step in selected_steps.items():
        coordinate = int(coordinate_text)
        weights[coordinate] = prefix_value(weights[coordinate], int(step))
    return weights


def derive_raw_support_coordinates(
    fixture: dict[str, Any],
    weights: list[float],
    baseline: list[float],
    target: list[float],
) -> tuple[list[int], list[int]]:
    rows = fixture["operator"]["rows"]
    mismatch_rows = [
        index
        for index, (actual, expected) in enumerate(zip(baseline, target))
        if bits(actual) != bits(expected)
    ]
    mismatch_set = set(mismatch_rows)
    interior = set(fixture["interior_indices"])
    supported = {
        coordinate
        for row_index in mismatch_set
        for coordinate in set(rows[row_index])
        if fixture["permitted"][coordinate]
        and coordinate in interior
    }
    legal = sorted(
        coordinate
        for coordinate in supported
        if any(legal_value(weights[coordinate], choice) is not None for choice in (-1, 1))
    )
    return mismatch_rows, legal


def run_dry(protocol_root: Path) -> Path:
    counts = audit_parent(protocol_root)
    repo_root = protocol_root.parents[2]
    event, _set_record, da2_result = load_event(repo_root)
    rmt_endpoint_path = (
        repo_root
        / "experiments/drosophila-heresy/q10-rmt-v1/qualification/sample-9731-9732/endpoints.json"
    )
    rmt_endpoints = json.loads(rmt_endpoint_path.read_text(encoding="utf-8"))
    endpoint = next(
        item
        for item in rmt_endpoints
        if item["source_event"] == SOURCE_EVENT and item["set_index"] == SET_INDEX
    )
    fixture = event["fixture"]
    rows = fixture["operator"]["rows"]
    initial = [from_bits(raw) for raw in fixture["initial_weight_bits"]]
    target_weights = [from_bits(raw) for raw in fixture["target_weight_bits"]]
    baseline_weights = reconstruct_weights(fixture, da2_result["selected_steps"])
    baseline = sequential_readout(rows, baseline_weights)
    target = sequential_readout(rows, target_weights)
    expected_endpoint = f"{SOURCE_EVENT}#set{SET_INDEX}"
    if endpoint.get("endpoint") != expected_endpoint:
        raise QualificationError("RMT endpoint identity mismatch")
    endpoint_rows = endpoint["rows"]
    if [bits(baseline[row["row"]]) for row in endpoint_rows] != [
        int(row["baseline_bits"]) for row in endpoint_rows
    ]:
        raise QualificationError("reconstructed baseline readout does not match sealed RMT rows")
    if [bits(target[row["row"]]) for row in endpoint_rows] != [
        int(row["target_bits"]) for row in endpoint_rows
    ]:
        raise QualificationError("reconstructed target readout does not match sealed RMT rows")
    mismatch_rows, legal_coordinates = derive_raw_support_coordinates(
        fixture, baseline_weights, baseline, target
    )
    selected_coordinates = legal_coordinates[:3]
    prefix_records = []
    for coordinate in selected_coordinates:
        domain = prefix_domain(baseline_weights[coordinate])
        for choice in domain:
            candidate_weights = baseline_weights[:]
            candidate_weights[coordinate] = prefix_value(candidate_weights[coordinate], choice)
            readout = sequential_readout(rows, candidate_weights)
            prefix_records.append(
                {
                    "coordinate": coordinate,
                    "choice": choice,
                    "stored_value_bits": bits(candidate_weights[coordinate]),
                    "readout_mismatch_count": sum(
                        bits(actual) != bits(expected)
                        for actual, expected in zip(readout, target)
                    ),
                }
            )
    output = protocol_root / "qualification/dry-run/receipt.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    receipt = {
        "protocol": "Q10-PF5",
        "status": "DRY_RUN_VALID__ONE_ENDPOINT_PREFIX_REPLAY",
        "engineering_only": True,
        "source_event": SOURCE_EVENT,
        "set_index": SET_INDEX,
        "endpoint": expected_endpoint,
        "parent_counts": counts,
        "coordinate_count": len(fixture["initial_weight_bits"]),
        "row_count": len(rows),
        "mismatch_rows": len(mismatch_rows),
        "raw_support_legal_coordinates": len(legal_coordinates),
        "selected_coordinates": selected_coordinates,
        "prefix_choice_count": len(prefix_records),
        "prefix_records": prefix_records,
        "baseline_target_bitwise_match": True,
        "execution_scope": {
            "state": "cloned_f32_only",
            "science": False,
            "behavioral_probe": False,
            "canonical_update": False,
        },
    }
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return output


def main() -> int:
    protocol_root = Path(__file__).resolve().parents[1]
    try:
        output = run_dry(protocol_root)
    except (OSError, KeyError, TypeError, ValueError, QualificationError) as error:
        raise SystemExit(f"Q10-PF5 dry run failed: {error}") from error
    print(f"Q10-PF5 dry run passed: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
