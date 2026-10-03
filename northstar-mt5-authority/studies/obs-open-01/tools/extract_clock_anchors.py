#!/usr/bin/env python3
"""Extract preregistered clock-anchor rows without exposing market summaries."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--anchors", required=True, help="comma-separated YYYY-MM-DD dates")
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    anchors = frozenset(part.strip() for part in args.anchors.split(",") if part.strip())
    if not anchors:
        raise ValueError("at least one anchor is required")
    args.output.mkdir(parents=True, exist_ok=True)
    output = args.output / "broker_clock_anchors.tsv"
    counts = {anchor: {"M1": 0, "M5": 0} for anchor in sorted(anchors)}

    with args.source.open(newline="", encoding="utf-8-sig") as source, output.open(
        "w", newline="", encoding="utf-8"
    ) as target:
        reader = csv.DictReader(source, delimiter="\t")
        if reader.fieldnames is None:
            raise ValueError("source header missing")
        writer = csv.DictWriter(target, fieldnames=reader.fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in reader:
            day = row["source_day"].replace(".", "-")
            if day not in anchors:
                continue
            timeframe = row["timeframe"]
            if timeframe not in ("M1", "M5"):
                raise ValueError(f"unexpected timeframe {timeframe}")
            counts[day][timeframe] += 1
            writer.writerow(row)

    receipt = {
        "schema": "OBS_OPEN_CLOCK_ANCHOR_EXTRACTION_V1",
        "anchors": sorted(anchors),
        "row_counts": counts,
        "source_bytes": args.source.stat().st_size,
        "source_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
        "output_bytes": output.stat().st_size,
        "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "substantive_fields_summarized": False,
    }
    receipt["logical_sha256"] = hashlib.sha256(canonical_json(receipt)).hexdigest()
    (args.output / "broker_clock_anchors_receipt.json").write_bytes(canonical_json(receipt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
