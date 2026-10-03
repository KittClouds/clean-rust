#!/usr/bin/env python3
"""Compare black-box MQL5 buffers with the independent opening-range oracle."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


FIELDS = [
    "range_high", "range_low", "range_mid", "range_width", "lifecycle",
    "range_open", "range_closed", "area_active", "interaction_eligible",
    "location", "grammar_event", "outside_run", "first_outside_side",
    "above_excursions", "below_excursions", "failed_above", "failed_below",
]
TOLERANCE = 1e-9


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def read_rows(path: Path, anchor: str) -> dict[tuple[int, int], dict[str, str]]:
    rows: dict[tuple[int, int], dict[str, str]] = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if not row["bar_open_time"].startswith(anchor.replace("-", ".")):
                continue
            key = (int(row["range_minutes"]), int(row["bar_open_epoch"]))
            if key in rows:
                raise ValueError(f"duplicate key {key} in {path}")
            rows[key] = row
    return rows


def equal(left: str, right: str) -> bool:
    if left == right:
        return True
    if left == "NOT_AVAILABLE" or right == "NOT_AVAILABLE":
        return False
    try:
        return abs(float(left) - float(right)) <= TOLERANCE
    except ValueError:
        return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--anchor", required=True)
    parser.add_argument("--actual", required=True, type=Path)
    parser.add_argument("--oracle", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    actual = read_rows(args.actual, args.anchor)
    oracle = read_rows(args.oracle, args.anchor)
    actual_keys = set(actual)
    oracle_keys = set(oracle)
    mismatches: list[dict[str, object]] = []
    for key in sorted(actual_keys & oracle_keys):
        for field in FIELDS:
            if not equal(actual[key][field], oracle[key][field]):
                mismatches.append({
                    "range_minutes": key[0],
                    "bar_open_epoch": key[1],
                    "field": field,
                    "actual": actual[key][field],
                    "oracle": oracle[key][field],
                })

    mismatch_path = args.output / "parity_mismatches.tsv"
    with mismatch_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["range_minutes", "bar_open_epoch", "field", "actual", "oracle"],
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(mismatches)

    passed = actual_keys == oracle_keys and not mismatches
    receipt = {
        "schema": "OBS_OPEN_PARITY_COMPARISON_V1",
        "anchor": args.anchor,
        "outcome": "PASS" if passed else "FAIL",
        "actual_rows": len(actual),
        "oracle_rows": len(oracle),
        "missing_actual_keys": len(oracle_keys - actual_keys),
        "unexpected_actual_keys": len(actual_keys - oracle_keys),
        "compared_cells": len(actual_keys & oracle_keys) * len(FIELDS),
        "mismatch_cells": len(mismatches),
        "actual_sha256": hashlib.sha256(args.actual.read_bytes()).hexdigest(),
        "oracle_sha256": hashlib.sha256(args.oracle.read_bytes()).hexdigest(),
        "mismatch_sha256": hashlib.sha256(mismatch_path.read_bytes()).hexdigest(),
    }
    receipt["logical_sha256"] = hashlib.sha256(canonical_json(receipt)).hexdigest()
    (args.output / "parity_comparison_receipt.json").write_bytes(canonical_json(receipt))
    return 0 if passed else 4


if __name__ == "__main__":
    raise SystemExit(main())
