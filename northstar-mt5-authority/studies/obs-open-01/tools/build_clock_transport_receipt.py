#!/usr/bin/env python3
"""Seal multi-regime clock transport without reading observer outcomes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--clock-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def expected_offset(day: str, proxy: ZoneInfo) -> int:
    instant = datetime.fromisoformat(day).replace(hour=12, tzinfo=timezone.utc)
    delta = instant.astimezone(proxy).utcoffset()
    if delta is None:
        raise ValueError(f"no UTC offset for {day}")
    return int(delta.total_seconds() // 60)


def main() -> int:
    args = parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    clock = contract["clock"]
    proxy = ZoneInfo(clock["server_offset_proxy_timezone"])
    args.output.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, object]] = []
    required_pass = True
    for day in clock["required_anchor_dates"]:
        parity_path = args.clock_root / f"alignment-{day}" / "clock_parity_receipt.json"
        fixture_path = args.clock_root / f"dukascopy-{day}" / "dukascopy_fixture_receipt.json"
        expected = expected_offset(day, proxy)
        if not parity_path.exists() or not fixture_path.exists():
            required_pass = False
            rows.append({
                "anchor": day,
                "expected_offset_minutes": expected,
                "observed_offset_minutes": "",
                "aligned_returns": 0,
                "pearson": "",
                "sign_agreement": "",
                "pearson_margin": "",
                "parity_outcome": "NOT_EVALUABLE_SOURCE_COVERAGE",
                "transport_outcome": "NOT_EVALUABLE_SOURCE_COVERAGE",
                "parity_receipt_sha256": "",
                "fixture_receipt_sha256": "",
            })
            continue
        parity = json.loads(parity_path.read_text(encoding="utf-8"))
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        observed = parity["best"]["offset_minutes"]
        outcome = (
            "PASS"
            if parity["outcome"] == "PASS_BOUNDED_SESSION" and observed == expected
            else "FAIL"
        )
        required_pass &= outcome == "PASS"
        rows.append({
            "anchor": day,
            "expected_offset_minutes": expected,
            "observed_offset_minutes": observed,
            "aligned_returns": parity["best"]["aligned_returns"],
            "pearson": parity["best"]["pearson"],
            "sign_agreement": parity["best"]["sign_agreement"],
            "pearson_margin": parity["pearson_margin"],
            "parity_outcome": parity["outcome"],
            "transport_outcome": outcome,
            "parity_receipt_sha256": sha256(parity_path),
            "fixture_receipt_sha256": sha256(fixture_path),
        })

    matrix_path = args.output / "clock_transport_matrix.tsv"
    with matrix_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    receipt = {
        "schema": "OBS_OPEN_CLOCK_TRANSPORT_RECEIPT_V1",
        "study_id": contract["study_id"],
        "outcome": "QUALIFIED" if required_pass else "NOT_EVALUABLE_CLOCK_TRANSPORT",
        "required_anchors": len(rows),
        "qualified_anchors": sum(row["transport_outcome"] == "PASS" for row in rows),
        "server_offset_model": clock["server_offset_model"],
        "server_offset_proxy_timezone": clock["server_offset_proxy_timezone"],
        "scientific_timezone": clock["scientific_timezone"],
        "unresolved_intervals": clock["excluded_unresolved_intervals"],
        "contract_sha256": sha256(args.contract),
        "matrix_sha256": sha256(matrix_path),
        "substantive_observer_outputs_read": False,
    }
    receipt["logical_sha256"] = hashlib.sha256(canonical_json(receipt)).hexdigest()
    (args.output / "clock_transport_receipt.json").write_bytes(canonical_json(receipt))
    return 0 if required_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
