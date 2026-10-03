#!/usr/bin/env python3
"""Evaluate the frozen OBS-OPEN-01 bounded clock-parity contract."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path


MIN_OVERLAP = 300
MIN_CORRELATION = 0.80
MIN_SIGN_AGREEMENT = 0.70
MIN_MARGIN = 0.30
OFFSETS = range(-720, 841, 15)


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def read_broker(path: Path, anchor: str) -> dict[int, float]:
    observations: dict[int, float] = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            source_day = row.get("anchor_date", row.get("source_day", ""))
            if source_day.replace(".", "-") != anchor or row["timeframe"] != "M1":
                continue
            observations[int(row["server_epoch"])] = float(row["close"])
    return observations


def read_external(path: Path) -> dict[int, float]:
    observations: dict[int, float] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            observations[int(row["utc_minute_epoch"])] = int(row["mid_sum"]) / int(row["mid_divisor"])
    return observations


def pearson(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return float("nan")
    mean_left = sum(left) / len(left)
    mean_right = sum(right) / len(right)
    numerator = sum((x - mean_left) * (y - mean_right) for x, y in zip(left, right))
    denom_left = sum((x - mean_left) ** 2 for x in left)
    denom_right = sum((y - mean_right) ** 2 for y in right)
    denominator = math.sqrt(denom_left * denom_right)
    return numerator / denominator if denominator else float("nan")


def compare(broker: dict[int, float], external: dict[int, float], offset_minutes: int) -> dict[str, object]:
    offset_seconds = offset_minutes * 60
    aligned = sorted((server_time, server_price, external[server_time - offset_seconds])
                     for server_time, server_price in broker.items()
                     if server_time - offset_seconds in external)
    broker_change: list[float] = []
    external_change: list[float] = []
    signs_equal = 0
    signs_compared = 0
    for previous, current in zip(aligned, aligned[1:]):
        if current[0] - previous[0] != 60:
            continue
        left = current[1] - previous[1]
        right = current[2] - previous[2]
        broker_change.append(left)
        external_change.append(right)
        if left != 0 and right != 0:
            signs_compared += 1
            signs_equal += (left > 0) == (right > 0)
    correlation = pearson(broker_change, external_change)
    return {
        "offset_minutes": offset_minutes,
        "aligned_minutes": len(aligned),
        "aligned_returns": len(broker_change),
        "pearson": None if math.isnan(correlation) else correlation,
        "nonzero_sign_pairs": signs_compared,
        "sign_agreement": signs_equal / signs_compared if signs_compared else None,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--anchor", required=True)
    parser.add_argument("--broker-bars", required=True, type=Path)
    parser.add_argument("--external-minutes", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    broker = read_broker(args.broker_bars, args.anchor)
    external = read_external(args.external_minutes)
    rows = [compare(broker, external, offset) for offset in OFFSETS]
    ranked = sorted(rows, key=lambda row: (
        2.0 if row["pearson"] is None else -float(row["pearson"]),
        -int(row["aligned_returns"]),
        int(row["offset_minutes"]),
    ))
    best, runner_up = ranked[0], ranked[1]
    margin = None if best["pearson"] is None or runner_up["pearson"] is None else float(best["pearson"]) - float(runner_up["pearson"])
    passed = (
        int(best["aligned_returns"]) >= MIN_OVERLAP
        and best["pearson"] is not None and float(best["pearson"]) >= MIN_CORRELATION
        and best["sign_agreement"] is not None and float(best["sign_agreement"]) >= MIN_SIGN_AGREEMENT
        and margin is not None and margin >= MIN_MARGIN
    )
    outcome = "PASS_BOUNDED_SESSION" if passed else "FAIL_ALIGNMENT_THRESHOLDS"

    scan_path = args.output / "clock_offset_scan.tsv"
    with scan_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    receipt = {
        "schema": "OBS_OPEN_CLOCK_PARITY_RECEIPT_V1",
        "anchor": args.anchor,
        "outcome": outcome,
        "best": best,
        "runner_up": runner_up,
        "pearson_margin": margin,
        "thresholds": {
            "minimum_aligned_returns": MIN_OVERLAP,
            "minimum_pearson_correlation": MIN_CORRELATION,
            "minimum_nonzero_sign_agreement": MIN_SIGN_AGREEMENT,
            "minimum_best_runner_up_correlation_margin": MIN_MARGIN,
        },
        "broker_rows": len(broker),
        "external_rows": len(external),
        "broker_sha256": hashlib.sha256(args.broker_bars.read_bytes()).hexdigest(),
        "external_sha256": hashlib.sha256(args.external_minutes.read_bytes()).hexdigest(),
        "scan_sha256": hashlib.sha256(scan_path.read_bytes()).hexdigest(),
        "scope": "ADMITTED_SESSION_ONLY",
        "winter_transport": "NOT_EVALUABLE_SOURCE_COVERAGE",
        "dst_transition_transport": "NOT_EVALUABLE_SOURCE_COVERAGE",
    }
    receipt["logical_sha256"] = hashlib.sha256(canonical_json(receipt)).hexdigest()
    (args.output / "clock_parity_receipt.json").write_bytes(canonical_json(receipt))
    return 0 if passed else 3


if __name__ == "__main__":
    raise SystemExit(main())
