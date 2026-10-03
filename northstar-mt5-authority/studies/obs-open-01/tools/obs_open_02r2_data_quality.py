"""Outcome-blind, discovery-prefix-only source quality audit for OBS-OPEN."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo


HEADER = (
    "schema", "source_day", "timeframe", "server_epoch", "server_time",
    "open", "high", "low", "close", "tick_volume", "spread", "real_volume",
)
SCHEMA = "OBS_OPEN_SOURCE_COVERAGE_V1"
CUTOFF = date(2025, 6, 30)


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def minute_epoch(day: date, local_time: time, offset_minutes: int) -> int:
    ny = ZoneInfo("America/New_York")
    instant = datetime.combine(day, local_time, ny).astimezone(timezone.utc)
    server_wall = instant + timedelta(minutes=offset_minutes)
    return int(server_wall.timestamp())


def load_metadata(partition: Path, census: Path) -> tuple[list[dict[str, str]], int, int]:
    with partition.open(newline="", encoding="utf-8") as handle:
        discovery = [row for row in csv.DictReader(handle, delimiter="\t") if row["partition"] == "DISCOVERY"]
    if len(discovery) != 257 or max(date.fromisoformat(row["civil_date"]) for row in discovery) != CUTOFF:
        raise ValueError("frozen discovery partition mismatch")
    with census.open(newline="", encoding="utf-8") as handle:
        coverage = list(csv.DictReader(handle, delimiter="\t"))
    prefix_rows = sum(
        int(row["source_day_m1_rows"]) + int(row["source_day_m5_rows"])
        for row in coverage if date.fromisoformat(row["civil_date"]) <= CUTOFF
    )
    safe_rows = sum(
        int(row["source_day_m1_rows"]) + int(row["source_day_m5_rows"])
        for row in coverage if date.fromisoformat(row["civil_date"]) < CUTOFF
    )
    return discovery, prefix_rows, safe_rows


def bounded_prefix_lines(source: Path, safe_rows: int, total_rows: int):
    """Yield the discovery prefix without requesting the first confirmation row.

    Buffered reads stop one full discovery day early. The final discovery day is
    then consumed from an unbuffered handle for an exact row-count boundary.
    """
    with source.open("rb") as handle:
        yield handle.readline()
        for _ in range(safe_rows):
            raw = handle.readline()
            if not raw:
                raise ValueError("source ended before safe discovery prefix")
            yield raw
        tail_offset = handle.tell()
    with source.open("rb", buffering=0) as handle:
        handle.seek(tail_offset)
        for _ in range(total_rows - safe_rows):
            raw = handle.readline()
            if not raw:
                raise ValueError("source ended before final discovery day")
            yield raw


def expected_windows(
    discovery: list[dict[str, str]],
) -> tuple[dict[str, set[int]], dict[int, str], dict[int, str], dict[int, str]]:
    expected: dict[str, set[int]] = {"M1": set(), "M5": set()}
    m1_owner: dict[int, str] = {}
    m1_required_owner: dict[int, str] = {}
    m5_owner: dict[int, str] = {}
    for row in discovery:
        day = date.fromisoformat(row["civil_date"])
        start = minute_epoch(day, time(9, 30), int(row["server_offset_minutes"]))
        for index in range(395):
            epoch = start + index * 60
            expected["M1"].add(epoch)
            m1_owner[epoch] = row["session_id"]
            if index < 30:
                m1_required_owner[epoch] = row["session_id"]
        for index in range(79):
            epoch = start + index * 300
            expected["M5"].add(epoch)
            m5_owner[epoch] = row["session_id"]
    return expected, m1_owner, m1_required_owner, m5_owner


def audit(source: Path, partition: Path, census: Path, authority_manifest: Path) -> dict[str, object]:
    manifest = json.loads(authority_manifest.read_text(encoding="utf-8"))
    authority = next(row for row in manifest["artifacts"] if row["kind"] == "BROKER_BAR_AUTHORITY")
    if source.stat().st_size != authority["bytes"]:
        raise ValueError("source byte size differs from frozen authority")
    discovery, prefix_rows, safe_rows = load_metadata(partition, census)
    expected, _m1_owner, m1_required_owner, m5_owner = expected_windows(discovery)
    retained: dict[str, dict[int, tuple[Decimal, Decimal, Decimal, Decimal]]] = {
        "M1": {}, "M5": {},
    }
    anomaly = Counter()
    timeframe_rows = Counter()
    prior_epoch = {"M1": -1, "M5": -1}
    seen: set[tuple[str, int]] = set()
    prefix_hash = hashlib.sha256()
    last_day = ""

    stream = bounded_prefix_lines(source, safe_rows, prefix_rows)
    header = next(stream)
    prefix_hash.update(header)
    decoded_header = tuple(header.decode("utf-8-sig").rstrip("\r\n").split("\t"))
    if decoded_header != HEADER:
        raise ValueError("source schema mismatch")
    for raw in stream:
            prefix_hash.update(raw)
            values = raw.decode("utf-8").rstrip("\r\n").split("\t")
            if len(values) != len(HEADER):
                anomaly["COLUMN_COUNT"] += 1
                continue
            row = dict(zip(HEADER, values))
            if row["schema"] != SCHEMA:
                anomaly["SCHEMA"] += 1
            source_day = row["source_day"].replace(".", "-")
            if source_day > CUTOFF.isoformat():
                anomaly["CONFIRMATION_BOUNDARY_CROSSED"] += 1
                continue
            if last_day and source_day < last_day:
                anomaly["SOURCE_DAY_ORDER"] += 1
            last_day = source_day
            timeframe = row["timeframe"]
            if timeframe not in ("M1", "M5"):
                anomaly["TIMEFRAME"] += 1
                continue
            timeframe_rows[timeframe] += 1
            try:
                epoch = int(row["server_epoch"])
                parsed = datetime.strptime(row["server_time"], "%Y.%m.%d %H:%M:%S").replace(tzinfo=timezone.utc)
                prices = tuple(Decimal(row[key]) for key in ("open", "high", "low", "close"))
                tick_volume, spread, real_volume = (int(row[key]) for key in ("tick_volume", "spread", "real_volume"))
            except (ValueError, InvalidOperation):
                anomaly["PARSE"] += 1
                continue
            if int(parsed.timestamp()) != epoch:
                anomaly["EPOCH_TIME_MISMATCH"] += 1
            quantum = 60 if timeframe == "M1" else 300
            if epoch % quantum:
                anomaly["TIMESTAMP_ALIGNMENT"] += 1
            key = (timeframe, epoch)
            if key in seen:
                anomaly["DUPLICATE"] += 1
            seen.add(key)
            if epoch <= prior_epoch[timeframe]:
                anomaly["NON_MONOTONIC"] += 1
            prior_epoch[timeframe] = epoch
            open_, high, low, close = prices
            if any(not value.is_finite() or value <= 0 for value in prices):
                anomaly["PRICE_DOMAIN"] += 1
            if high < max(open_, close, low) or low > min(open_, close, high):
                anomaly["OHLC_ORDER"] += 1
            if tick_volume < 0 or spread < 0 or real_volume < 0:
                anomaly["NEGATIVE_VOLUME_OR_SPREAD"] += 1
            if epoch in expected[timeframe]:
                retained[timeframe][epoch] = prices

    per_session_m1 = Counter(m1_required_owner[epoch] for epoch in retained["M1"] if epoch in m1_required_owner)
    per_session_m5 = Counter(m5_owner[epoch] for epoch in retained["M5"])
    session_coverage_failures = sum(
        per_session_m1[row["session_id"]] != 30 or per_session_m5[row["session_id"]] != 79
        for row in discovery
    )
    parity_missing = 0
    parity_mismatch = 0
    for epoch, m5 in sorted(retained["M5"].items()):
        pieces = [retained["M1"].get(epoch + offset * 60) for offset in range(5)]
        if any(piece is None for piece in pieces):
            parity_missing += 1
            continue
        complete = [piece for piece in pieces if piece is not None]
        derived = (complete[0][0], max(row[1] for row in complete), min(row[2] for row in complete), complete[-1][3])
        if derived != m5:
            parity_mismatch += 1

    issue_count = sum(anomaly.values()) + session_coverage_failures + parity_mismatch
    receipt: dict[str, object] = {
        "schema": "OBS_OPEN_DISCOVERY_SOURCE_QUALITY_V1",
        "scope": "DISCOVERY_SOURCE_ONLY_OUTCOME_BLIND",
        "outcome": "PASS" if issue_count == 0 else "FAIL",
        "source_authority_sha256_declared": authority["sha256"],
        "source_authority_bytes_verified": source.stat().st_size,
        "source_full_hash_recomputed": False,
        "discovery_prefix_rows_requested": prefix_rows,
        "buffered_safe_rows_before_final_discovery_day": safe_rows,
        "unbuffered_final_discovery_day_rows": prefix_rows - safe_rows,
        "discovery_prefix_sha256": prefix_hash.hexdigest(),
        "next_row_requested": False,
        "confirmation_rows_read": 0,
        "discovery_sessions": len(discovery),
        "source_rows_by_timeframe": dict(sorted(timeframe_rows.items())),
        "retained_window_rows": {key: len(value) for key, value in sorted(retained.items())},
        "session_window_expectation": {"M1_REQUIRED_OPENING": 30, "M5_REQUIRED_HORIZON": 79},
        "session_coverage_failures": session_coverage_failures,
        "m5_ohlc_parity_comparisons": len(retained["M5"]) - parity_missing,
        "m5_ohlc_missing_underlying": parity_missing,
        "m5_ohlc_missing_underlying_status": "PARITY_NOT_EVALUABLE_NONAUTHORITATIVE_M1_SUFFIX",
        "m5_ohlc_mismatches": parity_mismatch,
        "anomalies": dict(sorted(anomaly.items())),
        "issue_count": issue_count,
        "substantive_measurements_computed": False,
        "economic_authority": False,
        "trading_authority": False,
    }
    logical = dict(receipt)
    receipt["logical_sha256"] = hashlib.sha256(canonical_json(logical)).hexdigest()
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--partition", required=True, type=Path)
    parser.add_argument("--census", required=True, type=Path)
    parser.add_argument("--authority-manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    receipt = audit(args.source, args.partition, args.census, args.authority_manifest)
    args.output.write_bytes(canonical_json(receipt))
    print(receipt["outcome"])
    return 0 if receipt["outcome"] == "PASS" else 4


if __name__ == "__main__":
    raise SystemExit(main())
