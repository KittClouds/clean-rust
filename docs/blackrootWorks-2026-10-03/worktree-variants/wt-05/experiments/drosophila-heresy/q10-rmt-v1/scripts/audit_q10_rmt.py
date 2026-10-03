"""Independent baseline, ULP, and receipt audit for Q10-RMT."""
from __future__ import annotations

import hashlib
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


def sequential(row, weights):
    value = from_bits(0x80000000)
    for coordinate in row:
        value = f32(value + weights[coordinate])
    return value


def nextafter32(value, upward):
    return from_bits(bits(value) + (1 if upward else -1))


def step_value(value, step):
    for _ in range(abs(step)):
        value = nextafter32(value, step > 0)
    return value


def canonical_zero(raw):
    return 0x80000000 if (raw & 0x7FFFFFFF) == 0 else raw


def ordered(raw):
    raw = canonical_zero(raw)
    magnitude = raw & 0x7FFFFFFF
    return 0x80000000 - magnitude if raw & 0x80000000 else 0x80000000 + raw


def ulp(left, right):
    return abs(ordered(bits(left)) - ordered(bits(right)))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: audit_q10_rmt.py OUTPUT")
    root = Path(sys.argv[1]).resolve()
    protocol_root = root.parents[1]
    seal = json.loads((protocol_root / "PREEXECUTION.json").read_text())
    execution = json.loads((root / "execution.json").read_text())
    endpoints = json.loads((root / "endpoints.json").read_text())
    rows = json.loads((root / "rows.json").read_text())
    components = json.loads((root / "components.json").read_text())
    excluded = json.loads((root / "excluded-noncontract.json").read_text())
    authority_summary = json.loads((root / "authority-summary.json").read_text())
    assert seal["protocol"] == "Q10-RMT"
    assert seal["status"] == "FROZEN_PRE_EXECUTION"
    for entry in seal["source_manifest"]:
        assert digest(protocol_root / entry["path"]) == entry["sha256"]
    assert execution["status"] == "Q10_RMT_VALID__TOPOLOGY_MAPPED"
    assert execution["primary_valid_endpoints"] == 28
    assert execution["excluded_noncontract_endpoints"] == 4
    assert execution["repair_applied"] is False
    assert execution["behavioral_inference"] is False
    assert execution["scientific_seed_bundles_used"] == 0
    assert execution["dh08b_authorized"] is False
    assert len(endpoints) == 28
    assert len(excluded) == 4
    assert execution["local_replay_checks"] == execution["local_replay_passes"]
    source = Path(seal["input_root"])
    for path in sorted(source.glob("seed*.json")):
        assert digest(path) == seal["input_sha256"][path.name]
    da2 = Path(seal["parent_root"])
    assert digest(da2 / "qualification/sample-9731-9732/results.json") == seal["da2-results-sha256"]
    da2_results = json.loads((da2 / "qualification/sample-9731-9732/results.json").read_text())
    da2_lookup = {(item["source_event"], item["set_index"]): item for item in da2_results}
    expected_valid_order = [(item["source_event"], item["set_index"]) for item in da2_results if item["status"] == "DA2_GEOMETRY_PASS"]
    expected_valid = set(expected_valid_order)
    expected_excluded = {(item["source_event"], item["set_index"]) for item in da2_results if item["status"] != "DA2_GEOMETRY_PASS"}
    actual_valid = {(item["source_event"], item["set_index"]) for item in endpoints}
    actual_excluded = {(item["source_event"], item["set_index"]) for item in excluded}
    assert actual_valid == expected_valid
    assert actual_excluded == expected_excluded
    assert len(actual_valid) == len(endpoints) == 28
    assert len(actual_excluded) == len(excluded) == 4
    shard_receipts = execution["shard_receipts"]
    assert execution["shards"] == [item["path"] for item in shard_receipts]
    covered = []
    for receipt in shard_receipts:
        shard_root = protocol_root / receipt["path"]
        assert shard_root.is_dir()
        for name, expected_hash in receipt["sha256"].items():
            assert digest(shard_root / name) == expected_hash
        keys = [tuple(key) for key in receipt["endpoint_keys"]]
        start, stop = receipt["slice"]
        assert keys == expected_valid_order[start:stop]
        covered.extend(keys)
        assert receipt["endpoint_count"] == len(keys)
    assert covered == expected_valid_order
    events = {path.name: json.loads(path.read_text()) for path in sorted(source.glob("seed*.json"))}
    row_lookup = {}
    for record in rows:
        row_lookup.setdefault((record["endpoint"], record["set_index"], record["row"]), record)
    checked_rows = 0
    for endpoint in endpoints:
        event = events[endpoint["source_event"]]
        fixture = event["fixture"]
        weights = [from_bits(value) for value in fixture["initial_weight_bits"]]
        da2_result = da2_lookup[(endpoint["source_event"], endpoint["set_index"])]
        for coordinate, step in da2_result["selected_steps"].items():
            weights[int(coordinate)] = step_value(weights[int(coordinate)], int(step))
        target_weights = [from_bits(value) for value in fixture["target_weight_bits"]]
        target = [sequential(row, target_weights) for row in fixture["operator"]["rows"]]
        actual = [sequential(row, weights) for row in fixture["operator"]["rows"]]
        assert sum(bits(a) != bits(b) for a, b in zip(actual, target)) == endpoint["mismatch_count"]
        mismatches = [index for index, (a, b) in enumerate(zip(actual, target)) if bits(a) != bits(b)]
        assert len(mismatches) == endpoint["mismatch_count"]
        for row in mismatches:
            record = row_lookup[(endpoint["source_event"], endpoint["set_index"], row)]
            assert record["baseline_bits"] == bits(actual[row])
            assert record["target_bits"] == bits(target[row])
            assert record["baseline_ulp_distance"] == ulp(actual[row], target[row])
            checked_rows += 1
    move_lines = sum(1 for _ in (root / "moves.jsonl").open(encoding="utf-8"))
    assert move_lines == sum(endpoint["move_count_serialized"] for endpoint in endpoints)
    assert sum(item["mismatch_count"] for item in endpoints) == len(rows)
    assert authority_summary["mismatch_rows_total"] == len(rows)
    assert len(authority_summary["row_persistence"]) == max(item["total_rows"] for item in endpoints)
    for item in authority_summary["row_persistence"]:
        available = sum(endpoint["total_rows"] > item["row"] for endpoint in endpoints)
        assert item["endpoint_count"] == available
        assert item["mismatch_count"] == sum(record["row"] == item["row"] for record in rows)
        expected_persistence = item["mismatch_count"] / max(available, 1)
        assert abs(item["persistence"] - expected_persistence) <= 1.0e-15
    print(f"Q10-RMT independent audit passed: endpoints={len(endpoints)} rows={checked_rows} moves={move_lines} components={len(components)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
