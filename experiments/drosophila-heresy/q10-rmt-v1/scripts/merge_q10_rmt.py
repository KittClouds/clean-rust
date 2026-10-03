"""Merge deterministic Q10-RMT endpoint shards before independent audit."""
from __future__ import annotations

import json
import hashlib
import sys
from pathlib import Path


def load(root, name):
    return json.loads((root / name).read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main():
    if len(sys.argv) < 4:
        raise SystemExit("usage: merge_q10_rmt.py OUTPUT SHARD...")
    output = Path(sys.argv[1]).resolve()
    shards = [Path(path).resolve() for path in sys.argv[2:]]
    output.mkdir(parents=True, exist_ok=False)
    endpoints = []
    rows = []
    components = []
    excluded = []
    moves = []
    shard_receipts = []
    protocol_root = Path(__file__).parents[1].resolve()
    seal = load(protocol_root, "PREEXECUTION.json")
    da2_root = Path(seal["parent_root"])
    da2_results = load(da2_root / "qualification/sample-9731-9732", "results.json")
    valid_keys = [(item["source_event"], item["set_index"]) for item in da2_results if item["status"] == "DA2_GEOMETRY_PASS"]
    excluded_keys = [(item["source_event"], item["set_index"]) for item in da2_results if item["status"] != "DA2_GEOMETRY_PASS"]
    expected_excluded = None
    seen_keys = set()
    previous_stop = 0
    for shard in shards:
        shard_execution = load(shard, "execution.json")
        shard_endpoints = load(shard, "endpoints.json")
        shard_excluded = load(shard, "excluded-noncontract.json")
        shard_slice = shard_execution.get("primary_valid_endpoint_slice")
        if not isinstance(shard_slice, list) or len(shard_slice) != 2:
            raise SystemExit(f"missing shard slice: {shard}")
        start, stop = map(int, shard_slice)
        if start != previous_stop or stop <= start or stop > len(valid_keys):
            raise SystemExit(f"non-contiguous shard slice: {shard_slice}")
        expected_keys = valid_keys[start:stop]
        actual_keys = [(item["source_event"], item["set_index"]) for item in shard_endpoints]
        if actual_keys != expected_keys:
            raise SystemExit(f"shard endpoint identity mismatch: {shard}")
        if seen_keys.intersection(actual_keys):
            raise SystemExit(f"duplicate endpoint identity: {shard}")
        seen_keys.update(actual_keys)
        if [(item["source_event"], item["set_index"]) for item in shard_excluded] != excluded_keys:
            raise SystemExit(f"excluded endpoint mismatch: {shard}")
        if expected_excluded is None:
            expected_excluded = shard_excluded
        elif shard_excluded != expected_excluded:
            raise SystemExit(f"excluded receipt differs: {shard}")
        endpoints.extend(shard_endpoints)
        rows.extend(load(shard, "rows.json"))
        components.extend(load(shard, "components.json"))
        excluded = shard_excluded
        moves.append((shard / "moves.jsonl").read_bytes())
        shard_path = shard.relative_to(protocol_root).as_posix()
        shard_receipts.append({
            "path": shard_path,
            "sha256": {name: digest(shard / name) for name in (
                "endpoints.json", "rows.json", "components.json",
                "excluded-noncontract.json", "execution.json",
                "authority-summary.json", "moves.jsonl",
            )},
            "slice": [start, stop],
            "endpoint_keys": [list(key) for key in actual_keys],
            "endpoint_count": len(shard_endpoints),
            "row_count": len(load(shard, "rows.json")),
            "component_count": len(load(shard, "components.json")),
            "move_count": sum(1 for _ in (shard / "moves.jsonl").open(encoding="utf-8")),
        })
        previous_stop = stop
    if seen_keys != set(valid_keys) or previous_stop != len(valid_keys):
        raise SystemExit("shard coverage does not equal DA2 geometry-pass set")
    endpoints.sort(key=lambda item: (item["source_event"], item["set_index"]))
    rows.sort(key=lambda item: (item["endpoint"], item["row"]))
    components.sort(key=lambda item: (item["endpoint"], item["component_index"]))
    (output / "endpoints.json").write_text(json.dumps(endpoints, indent=2) + "\n")
    (output / "rows.json").write_text(json.dumps(rows, indent=2) + "\n")
    (output / "components.json").write_text(json.dumps(components, indent=2) + "\n")
    (output / "excluded-noncontract.json").write_text(json.dumps(excluded, indent=2) + "\n")
    with (output / "moves.jsonl").open("wb") as writer:
        for data in moves:
            writer.write(data)
    row_counts = {}
    total_rows = max((item["total_rows"] for item in endpoints), default=0)
    for item in rows:
        key = item["row"]
        row_counts[key] = row_counts.get(key, 0) + 1
    authority_summary = {
        "endpoint_count": len(endpoints),
        "excluded_noncontract_endpoints": len(excluded),
        "mismatch_rows_total": len(rows),
        "one_step_orphan_rows": sum(item["one_step_orphan_rows"] for item in endpoints),
        "one_step_fragile_rows": sum(item["one_step_fragile_rows"] for item in endpoints),
        "immediate_rows": sum(item["immediate_rows"] for item in endpoints),
        "threshold_gated_rows": sum(item["threshold_gated_rows"] for item in endpoints),
        "no_local_authority_rows": sum(item["final_no_local_authority_rows"] for item in endpoints),
        "largest_component_rows": max((item["largest_component_rows"] for item in endpoints), default=0),
        "largest_component_error_share": max((item["largest_component_error_share"] for item in endpoints), default=0.0),
        "row_persistence": [
            {
                "row": row,
                "mismatch_count": row_counts.get(row, 0),
                "endpoint_count": sum(item["total_rows"] > row for item in endpoints),
                "persistence": row_counts.get(row, 0) / max(sum(item["total_rows"] > row for item in endpoints), 1),
            }
            for row in range(total_rows)
        ],
    }
    (output / "authority-summary.json").write_text(json.dumps(authority_summary, indent=2) + "\n")
    merged = {
        "protocol": "Q10-RMT",
        "status": "Q10_RMT_VALID__TOPOLOGY_MAPPED",
        "declared_da2_endpoints": 32,
        "primary_valid_endpoints": len(endpoints),
        "excluded_noncontract_endpoints": len(excluded),
        "mismatch_rows_mapped": len(rows),
        "component_records": len(components),
        "repair_applied": False,
        "behavioral_inference": False,
        "scientific_seed_bundles_used": 0,
        "dh08b_authorized": False,
        "local_replay_checks": sum(item["local_replay_checks"] for item in endpoints),
        "local_replay_passes": sum(item["local_replay_passes"] for item in endpoints),
        "shards": [receipt["path"] for receipt in shard_receipts],
        "shard_receipts": shard_receipts,
        "next_decision": "Choose the next correction architecture from the sealed residual topology; do not open DH08B.",
    }
    (output / "execution.json").write_text(json.dumps(merged, indent=2) + "\n")
    print(f"merged Q10-RMT shards: endpoints={len(endpoints)} rows={len(rows)} components={len(components)}")


if __name__ == "__main__":
    main()
