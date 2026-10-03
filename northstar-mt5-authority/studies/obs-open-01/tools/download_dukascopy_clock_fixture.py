#!/usr/bin/env python3
"""Download and decode a bounded Dukascopy tick fixture for clock parity."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import lzma
import struct
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


RECORD = struct.Struct(">3i2f")
SCHEMA = "OBS_OPEN_DUKASCOPY_CLOCK_FIXTURE_V1"
SYMBOL = "USA30IDXUSD"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="UTC calendar date, YYYY-MM-DD")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--hours",
        default="0-23",
        help="UTC hours as comma-separated values or inclusive ranges (default: 0-23)",
    )
    parser.add_argument("--offline", action="store_true", help="rebuild only from the existing raw-bi5 directory")
    return parser.parse_args()


def parse_hours(spec: str) -> tuple[int, ...]:
    hours: set[int] = set()
    for part in spec.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            left, right = token.split("-", 1)
            hours.update(range(int(left), int(right) + 1))
        else:
            hours.add(int(token))
    if not hours or min(hours) < 0 or max(hours) > 23:
        raise ValueError(f"invalid UTC hour specification: {spec}")
    return tuple(sorted(hours))


def fetch_hour(day: date, hour: int, raw_root: Path, offline: bool) -> tuple[int, datetime, str, Path, bytes, str]:
    stamp = datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc)
    url = (
        f"https://datafeed.dukascopy.com/datafeed/{SYMBOL}/"
        f"{day.year:04d}/{day.month - 1:02d}/{day.day:02d}/{hour:02d}h_ticks.bi5"
    )
    destination = raw_root / f"{stamp:%Y%m%dT%H}0000Z.bi5"
    if destination.exists() and (destination.stat().st_size or offline):
        return hour, stamp, url, destination, destination.read_bytes(), ""
    if offline:
        return hour, stamp, url, destination, b"", "OFFLINE_SOURCE_MISSING"
    last_error = ""
    for _attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "OBS-OPEN-01/1.0"})
            with urllib.request.urlopen(request, timeout=15) as response:
                compressed = response.read()
            destination.write_bytes(compressed)
            return hour, stamp, url, destination, compressed, ""
        except Exception as exc:
            last_error = f"{type(exc).__name__}:{exc}"
    return hour, stamp, url, destination, b"", last_error


def main() -> int:
    args = parse_args()
    day = date.fromisoformat(args.date)
    requested_hours = parse_hours(args.hours)
    root = args.output.resolve()
    raw_root = root / "raw-bi5"
    raw_root.mkdir(parents=True, exist_ok=True)

    manifest_rows: list[dict[str, object]] = []
    minute_last: dict[int, tuple[int, int, int]] = {}
    total_ticks = 0

    with ThreadPoolExecutor(max_workers=8) as pool:
        fetched = list(pool.map(lambda hour: fetch_hour(day, hour, raw_root, args.offline), requested_hours))

    for hour, stamp, url, destination, compressed, fetch_error in sorted(fetched):
        name = destination.name
        status = "OK"
        error = fetch_error
        decoded = b""
        tick_count = 0

        try:
            if fetch_error:
                raise ValueError(fetch_error)
            if not compressed:
                status = "OK_EMPTY"
                decoded = b""
            else:
                decoded = lzma.decompress(compressed)
            if len(decoded) % RECORD.size:
                raise ValueError(f"decoded length {len(decoded)} is not a multiple of {RECORD.size}")
            for offset in range(0, len(decoded), RECORD.size):
                millis, ask, bid, _ask_volume, _bid_volume = RECORD.unpack_from(decoded, offset)
                if not 0 <= millis < 3_600_000:
                    raise ValueError(f"invalid millisecond offset {millis}")
                epoch_ms = int(stamp.timestamp()) * 1000 + millis
                minute_epoch = epoch_ms // 60_000 * 60
                mid_sum = ask + bid
                previous = minute_last.get(minute_epoch)
                if previous is None or epoch_ms >= previous[0]:
                    minute_last[minute_epoch] = (epoch_ms, mid_sum, 2)
                tick_count += 1
            total_ticks += tick_count
        except Exception as exc:  # receipt records the bounded source failure
            status = "ERROR"
            error = f"{type(exc).__name__}:{exc}"

        manifest_rows.append(
            {
                "utc_hour": stamp.isoformat(),
                "url": url,
                "relative_path": f"raw-bi5/{name}",
                "status": status,
                "compressed_bytes": len(compressed),
                "compressed_sha256": sha256_bytes(compressed) if compressed else "",
                "decoded_bytes": len(decoded),
                "tick_count": tick_count,
                "error": error,
            }
        )

    manifest_path = root / "dukascopy_hour_manifest.tsv"
    with manifest_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(manifest_rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(manifest_rows)

    minutes_path = root / "dukascopy_utc_minutes.tsv"
    with minutes_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["schema", "utc_minute_epoch", "utc_minute", "last_tick_epoch_ms", "mid_sum", "mid_divisor"])
        for minute_epoch, (tick_epoch_ms, mid_sum, divisor) in sorted(minute_last.items()):
            writer.writerow(
                [
                    SCHEMA,
                    minute_epoch,
                    datetime.fromtimestamp(minute_epoch, timezone.utc).isoformat(),
                    tick_epoch_ms,
                    mid_sum,
                    divisor,
                ]
            )

    receipt = {
        "schema": SCHEMA,
        "provider": "Dukascopy",
        "symbol": SYMBOL,
        "utc_date": args.date,
        "hours_requested": len(requested_hours),
        "utc_hours": list(requested_hours),
        "hours_ok": sum(str(row["status"]).startswith("OK") for row in manifest_rows),
        "hours_error": sum(not str(row["status"]).startswith("OK") for row in manifest_rows),
        "ticks_decoded": total_ticks,
        "minutes_emitted": len(minute_last),
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "minutes_sha256": hashlib.sha256(minutes_path.read_bytes()).hexdigest(),
    }
    receipt["logical_sha256"] = sha256_bytes(canonical_json(receipt))
    (root / "dukascopy_fixture_receipt.json").write_bytes(canonical_json(receipt))
    return 0 if receipt["hours_error"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
