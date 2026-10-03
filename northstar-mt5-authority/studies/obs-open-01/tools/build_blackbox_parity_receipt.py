#!/usr/bin/env python3
"""Seal two deterministic black-box observer runs into one compact receipt."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


FILES = (
    "OBS_OPEN_01_parity_run1_buffers.tsv",
    "OBS_OPEN_01_parity_run1_receipt.tsv",
    "parity_mismatches.tsv",
    "parity_comparison_receipt.json",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def one_row(path: Path) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if len(rows) != 1:
        raise ValueError(f"expected one receipt row in {path}, got {len(rows)}")
    return rows[0]


def validate_run(path: Path) -> tuple[dict[str, str], dict[str, object]]:
    missing = [name for name in FILES if not (path / name).is_file()]
    if missing:
        raise ValueError(f"missing run artifacts in {path}: {missing}")
    receipt = one_row(path / FILES[1])
    expected = {
        "schema": "OBS_OPEN_PARITY_BLACKBOX_V1",
        "symbol": "US30",
        "period": "PERIOD_M5",
        "start_hour": "16",
        "start_minute": "30",
        "area_end_hour": "23",
        "area_end_minute": "0",
        "handles_ok": "30",
        "rows": "8310",
        "copy_failures": "0",
        "readiness_deferrals": "0",
        "finalized_bar_rows": "30",
        "deinit_reason": "1",
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise ValueError(f"{path.name} {key}={receipt.get(key)!r}, expected {value!r}")
    comparison = json.loads((path / FILES[3]).read_text("utf-8"))
    required = {
        "schema": "OBS_OPEN_PARITY_COMPARISON_V1",
        "anchor": "2026-08-13",
        "outcome": "PASS",
        "actual_rows": 8280,
        "oracle_rows": 8280,
        "missing_actual_keys": 0,
        "unexpected_actual_keys": 0,
        "compared_cells": 140760,
        "mismatch_cells": 0,
    }
    for key, value in required.items():
        if comparison.get(key) != value:
            raise ValueError(
                f"{path.name} comparison {key}={comparison.get(key)!r}, expected {value!r}"
            )
    return receipt, comparison


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-a", type=Path, required=True)
    parser.add_argument("--run-b", type=Path, required=True)
    parser.add_argument("--collector-source", type=Path, required=True)
    parser.add_argument("--collector-binary", type=Path, required=True)
    parser.add_argument("--observer-source", type=Path, required=True)
    parser.add_argument("--observer-binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    _, comparison_a = validate_run(args.run_a)
    _, comparison_b = validate_run(args.run_b)
    hashes_a = {name: sha256(args.run_a / name) for name in FILES}
    hashes_b = {name: sha256(args.run_b / name) for name in FILES}
    if hashes_a != hashes_b:
        raise ValueError("repeat-run artifacts are not byte-identical")

    receipt = {
        "schema": "OBS_OPEN_BLACKBOX_PARITY_SEAL_V1",
        "study_id": "OBS-OPEN-01",
        "scope": "US30_2026-08-13_M5_R01_R30_BOUNDED_SESSION_ONLY",
        "outcome": "PASS",
        "frozen_observer_parity": "PASS",
        "replay_determinism": "PASS_BYTE_IDENTICAL",
        "clock_authority": "PASS_BOUNDED_SESSION_ONLY",
        "input_group_runtime_abi": "EXPLICIT_GROUP_STRINGS_REQUIRED",
        "rows": comparison_a["actual_rows"],
        "compared_cells": comparison_a["compared_cells"],
        "mismatch_cells": comparison_a["mismatch_cells"],
        "copy_failures": 0,
        "finalized_bar_rows": 30,
        "repeat_run_hashes": hashes_a,
        "collector_source_sha256": sha256(args.collector_source),
        "collector_binary_sha256": sha256(args.collector_binary),
        "observer_source_sha256": sha256(args.observer_source),
        "observer_binary_sha256": sha256(args.observer_binary),
        "oracle_sha256": comparison_a["oracle_sha256"],
        "run_a_comparison_logical_sha256": comparison_a["logical_sha256"],
        "run_b_comparison_logical_sha256": comparison_b["logical_sha256"],
        "substantive_results_status": "FROZEN_UNOPENED",
        "economic_authority": False,
        "trading_authority": False,
    }
    canonical = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    receipt["logical_sha256"] = hashlib.sha256(canonical).hexdigest()
    payload = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(payload)
    print(payload.decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
