#!/usr/bin/env python3
"""Extract an outcome-blind acquisition receipt from bars and the MT5 tester log."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--tester-log", required=True, type=Path)
    parser.add_argument("--collector-source", required=True, type=Path)
    parser.add_argument("--collector-ex5", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    counts: Counter[str] = Counter()
    first: dict[str, str] = {}
    last: dict[str, str] = {}
    with args.source.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            timeframe = row["timeframe"]
            counts[timeframe] += 1
            first.setdefault(timeframe, row["server_time"])
            last[timeframe] = row["server_time"]

    text = args.tester_log.read_text(encoding="utf-16")
    relevant = [
        line for line in text.splitlines()
        if "OBS_OPEN_SOURCE_COVERAGE_EA_" in line
        or "OBS_OPEN_SourceCoverageCollectorEA_v1.ex5 from 2024.01.01" in line
        or "1 minutes OHLC ticks generating" in line
        or ("650381 bars generated" in line and "US30,M1" in line)
    ]
    if not relevant:
        raise ValueError("collector execution not found in tester log")
    complete = next((line for line in reversed(relevant) if "_COMPLETE" in line), "")
    match = re.search(r"m1_rows=(\d+) m5_rows=(\d+)", complete)
    if match is None:
        raise ValueError("collector completion counts not found")
    if int(match.group(1)) != counts["M1"] or int(match.group(2)) != counts["M5"]:
        raise ValueError("collector log counts do not match bar authority")

    args.output.mkdir(parents=True, exist_ok=True)
    excerpt_path = args.output / "source_acquisition_terminal_excerpt.tsv"
    with excerpt_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["sequence", "terminal_log_line"])
        for index, line in enumerate(relevant):
            writer.writerow([index, line])
    receipt = {
        "schema": "OBS_OPEN_SOURCE_ACQUISITION_RECEIPT_V1",
        "outcome": "PASS",
        "symbol": "US30",
        "source": "MetaQuotes-Demo",
        "tester_model": "ONE_MINUTE_OHLC",
        "requested_interval": ["2024-01-01T00:00:00", "2026-01-02T00:00:00"],
        "emitted_interval": {"M1": [first["M1"], last["M1"]], "M5": [first["M5"], last["M5"]]},
        "row_counts": dict(sorted(counts.items())),
        "source_sha256": sha256(args.source),
        "collector_source_sha256": sha256(args.collector_source),
        "collector_ex5_sha256": sha256(args.collector_ex5),
        "terminal_excerpt_sha256": sha256(excerpt_path),
        "substantive_observer_outputs_requested": False,
        "substantive_observer_outputs_read": False,
    }
    receipt["logical_sha256"] = hashlib.sha256(canonical_json(receipt)).hexdigest()
    (args.output / "source_acquisition_receipt.json").write_bytes(canonical_json(receipt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
