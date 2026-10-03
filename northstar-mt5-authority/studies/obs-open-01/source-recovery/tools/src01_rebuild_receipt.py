"""Snapshot and compare deterministic SRC-01 upstream build artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


UPSTREAM = (
    "SRC01_authority_manifest.json",
    "SRC01_runtime_receipt.json",
    "SRC01_metrology_defect_receipt.json",
    "SRC01_M1_online_parity.json",
    "SRC01_M5_online_parity.json",
    "SRC01_M1_reload_parity_grouped_abi.json",
    "SRC01_M5_reload_parity_grouped_abi.json",
    "SRC01_reload_determinism.json",
    "SRC01_boundary_causal_receipt.json",
    "SRC01_synthetic_fixture_receipt.json",
)


def snapshot(root: Path) -> dict[str, object]:
    artifacts = []
    for name in UPSTREAM:
        path = root / name
        if not path.is_file():
            raise SystemExit(f"missing rebuild artifact: {path}")
        artifacts.append({"path": name, "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return {"schema": "OBS_OPEN_SRC01_REBUILD_SNAPSHOT_V1", "artifacts": artifacts}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path)
    parser.add_argument("--snapshot-a", type=Path)
    parser.add_argument("--snapshot-b", type=Path)
    parser.add_argument("--file-a", type=Path)
    parser.add_argument("--file-b", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.file_a and args.file_b:
        left_bytes = args.file_a.read_bytes()
        right_bytes = args.file_b.read_bytes()
        identical = left_bytes == right_bytes
        value = {
            "schema": "OBS_OPEN_SRC01_FINAL_SEAL_DETERMINISM_V1",
            "builds": 2,
            "build_a_sha256": hashlib.sha256(left_bytes).hexdigest(),
            "build_b_sha256": hashlib.sha256(right_bytes).hexdigest(),
            "byte_identical": identical,
            "status": "PASS" if identical else "FAIL",
        }
    elif args.root:
        value = snapshot(args.root)
    else:
        if not args.snapshot_a or not args.snapshot_b:
            raise SystemExit("comparison requires --snapshot-a and --snapshot-b")
        left = json.loads(args.snapshot_a.read_text(encoding="utf-8"))
        right = json.loads(args.snapshot_b.read_text(encoding="utf-8"))
        left_map = {item["path"]: item for item in left["artifacts"]}
        right_map = {item["path"]: item for item in right["artifacts"]}
        names = sorted(set(left_map) | set(right_map))
        rows = []
        for name in names:
            a, b = left_map.get(name), right_map.get(name)
            identical = a == b and a is not None
            rows.append({"path": name, "build_a": a, "build_b": b, "byte_identical": identical, "status": "PASS" if identical else "FAIL"})
        value = {
            "schema": "OBS_OPEN_SRC01_REBUILD_DETERMINISM_V1",
            "builds": 2,
            "rows": rows,
            "status": "PASS" if all(row["status"] == "PASS" for row in rows) else "FAIL",
        }
    args.output.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
