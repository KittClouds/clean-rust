#!/usr/bin/env python3
"""Independent deterministic R01-R30 oracle from raw M1/M5 broker bars."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


NA = "NOT_AVAILABLE"
SCHEMA = "OBS_OPEN_PARITY_ORACLE_V1"


@dataclass
class Track:
    previous: int = 0
    outside_run: int = 0
    last_open: datetime | None = None
    first_side: int = 0
    above: int = 0
    below: int = 0
    failed_above: int = 0
    failed_below: int = 0


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def load_bars(path: Path, anchor: str, timeframe: str) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [row for row in csv.DictReader(handle, delimiter="\t")
                if row["anchor_date"].replace(".", "-") == anchor and row["timeframe"] == timeframe]


def f(value: float | int) -> str:
    return f"{float(value):.12f}"


def location(close: float, high: float, low: float) -> int:
    if close > high:
        return 2
    if close < low:
        return 3
    return 1


def grammar(track: Track, loc: int, bar_open: datetime, continuous_required: bool = True) -> tuple[int, Track]:
    has_predecessor = track.last_open is not None
    continuous = has_predecessor and bar_open - track.last_open == timedelta(minutes=5)
    event = 0
    if has_predecessor and continuous_required and not continuous:
        event = {1: 12, 2: 13, 3: 14}[loc]
        track.previous = 0
        track.outside_run = 0
    previous = track.previous

    if event == 0:
        if loc == 1:
            if previous == 2:
                if track.outside_run == 1:
                    event = 4
                    track.failed_above += 1
                else:
                    event = 5
            elif previous == 3:
                if track.outside_run == 1:
                    event = 8
                    track.failed_below += 1
                else:
                    event = 9
            else:
                event = 1
        elif loc == 2:
            if previous == 2:
                event = 3
            elif previous == 3:
                event = 11
                track.above += 1
            else:
                event = 2
                track.above += 1
            if track.first_side == 0:
                track.first_side = 1
        else:
            if previous == 3:
                event = 7
            elif previous == 2:
                event = 10
                track.below += 1
            else:
                event = 6
                track.below += 1
            if track.first_side == 0:
                track.first_side = -1
    else:
        if loc == 2:
            track.above += 1
            if track.first_side == 0:
                track.first_side = 1
        elif loc == 3:
            track.below += 1
            if track.first_side == 0:
                track.first_side = -1

    if loc == 1:
        track.outside_run = 0
    elif loc == previous and previous != 0 and (continuous or not continuous_required):
        track.outside_run += 1
    else:
        track.outside_run = 1
    track.previous = loc
    track.last_open = bar_open
    return event, track


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--anchor", required=True)
    parser.add_argument("--broker-bars", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    m1 = load_bars(args.broker_bars, args.anchor, "M1")
    m5 = load_bars(args.broker_bars, args.anchor, "M5")
    day = datetime.fromisoformat(args.anchor)
    start = day.replace(hour=16, minute=30)
    horizon = day.replace(hour=23, minute=0)
    fields = [
        "schema", "range_minutes", "bar_open_epoch", "bar_open_time",
        "range_high", "range_low", "range_mid", "range_width", "lifecycle",
        "range_open", "range_closed", "area_active", "interaction_eligible",
        "location", "grammar_event", "outside_run", "first_outside_side",
        "above_excursions", "below_excursions", "failed_above", "failed_below",
    ]
    rows: list[dict[str, object]] = []

    for minutes in range(1, 31):
        freeze = start + timedelta(minutes=minutes)
        source = [row for row in m1 if start <= datetime.strptime(row["server_time"], "%Y.%m.%d %H:%M:%S") < freeze]
        evaluable = len(source) == minutes
        high = max((float(row["high"]) for row in source), default=0.0)
        low = min((float(row["low"]) for row in source), default=0.0)
        track = Track()
        for bar in m5:
            bar_open = datetime.strptime(bar["server_time"], "%Y.%m.%d %H:%M:%S")
            if bar_open < start:
                lifecycle = 0
            elif bar_open < freeze:
                lifecycle = 1
            elif not evaluable:
                lifecycle = -1
            elif bar_open < horizon:
                lifecycle = 2
            else:
                lifecycle = 3
            has_geometry = evaluable and lifecycle in (2, 3)
            eligible = evaluable and bar_open >= freeze and bar_open + timedelta(minutes=5) <= horizon
            loc: int | None = None
            event: int | None = None
            if eligible:
                loc = location(float(bar["close"]), high, low)
                event, track = grammar(track, loc, bar_open)

            rows.append({
                "schema": SCHEMA,
                "range_minutes": minutes,
                "bar_open_epoch": bar["server_epoch"],
                "bar_open_time": bar["server_time"],
                "range_high": f(high) if has_geometry else NA,
                "range_low": f(low) if has_geometry else NA,
                "range_mid": f((high + low) / 2) if has_geometry else NA,
                "range_width": f(high - low) if has_geometry else NA,
                "lifecycle": f(lifecycle),
                "range_open": f(lifecycle == 1),
                "range_closed": f(has_geometry),
                "area_active": f(evaluable and lifecycle == 2),
                "interaction_eligible": f(eligible),
                "location": f(loc) if loc is not None else NA,
                "grammar_event": f(event) if event is not None else NA,
                "outside_run": f(track.outside_run) if eligible else NA,
                "first_outside_side": f(track.first_side) if eligible else NA,
                "above_excursions": f(track.above) if eligible else NA,
                "below_excursions": f(track.below) if eligible else NA,
                "failed_above": f(track.failed_above) if eligible else NA,
                "failed_below": f(track.failed_below) if eligible else NA,
            })

    output = args.output / "opening_range_oracle.tsv"
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    receipt = {
        "schema": SCHEMA,
        "anchor": args.anchor,
        "range_count": 30,
        "m1_rows": len(m1),
        "m5_rows": len(m5),
        "oracle_rows": len(rows),
        "broker_sha256": hashlib.sha256(args.broker_bars.read_bytes()).hexdigest(),
        "oracle_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }
    receipt["logical_sha256"] = hashlib.sha256(canonical_json(receipt)).hexdigest()
    (args.output / "opening_range_oracle_receipt.json").write_bytes(canonical_json(receipt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
